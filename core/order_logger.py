from __future__ import annotations

from collections import deque
from collections.abc import Callable
from dataclasses import dataclass, field
import gzip
import io
import json
import os
from pathlib import Path
import threading
import time
from typing import Any

from exch.errors import aurora_guard_reason, normalize_reason_struct


def _to_ns(unit: str) -> int:
    """Return multiplier for unit string into nanoseconds.

    Accepted: 'ns' -> 1, 'ms' -> 1_000_000, 's' -> 1_000_000_000.
    """
    s = str(unit).strip().lower()
    if s == "ns":
        return 1
    if s == "ms":
        return 1_000_000
    if s == "s":
        return 1_000_000_000
    raise ValueError(f"unknown unit: {unit}")

# Terminal order states that should not be duplicated (legacy safeguard)
TERMINAL_STATES = {"FILLED", "CANCELLED", "EXPIRED"}


class _LRUSet:
    """A tiny LRU for de-duplication of arbitrary hashable keys."""
    def __init__(self, capacity: int = 8192) -> None:
        self.capacity = capacity
        self._dq: deque[Any] = deque()
        self._set: set[Any] = set()

    def add(self, key: Any) -> None:
        if key in self._set:
            return
        self._dq.append(key)
        self._set.add(key)
        if len(self._dq) > self.capacity:
            old = self._dq.popleft()
            self._set.discard(old)

    def contains(self, key: Any) -> bool:
        return key in self._set


class _FileLock:
    """Cross-platform advisory file lock on a dedicated lock file."""
    def __init__(self, lock_path: Path) -> None:
        self.lock_path = lock_path
        self._fh: io.TextIOWrapper | None = None
        self._mtx = threading.Lock()

    def __enter__(self):
        self._mtx.acquire()
        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        # Use a separate lock file to avoid interfering with data file renames
        self._fh = open(self.lock_path, "a+")
        try:
            try:
                import fcntl  # type: ignore
                fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)  # type: ignore[attr-defined]
            except Exception:
                # Windows
                try:
                    import msvcrt  # type: ignore
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_LOCK, 1)
                except Exception:
                    pass
        except Exception:
            pass
        return self

    def __exit__(self, exc_type, exc, tb):
        try:
            if self._fh is not None:
                try:
                    try:
                        import fcntl  # type: ignore
                        fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)  # type: ignore[attr-defined]
                    except Exception:
                        try:
                            import msvcrt  # type: ignore
                            msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
                        except Exception:
                            pass
                finally:
                    self._fh.close()
        finally:
            self._fh = None
            self._mtx.release()


class _JsonlWriter:
    """Append-only JSONL writer with daily+size rotation, gzip on roll, and retention cleanup.

    - current file is plain JSONL at base_path
    - on rotation, the file is renamed to base_path.YYYYMMDD.HHMMSS.partN.jsonl and gzipped to .gz
    - retention_days controls deletion of .gz archives older than N days
    """

    def __init__(
        self,
        base_path: Path,
        max_bytes: int = 200 * 1024 * 1024,
        retention_days: int = 7,
        compress: bool = True,
        retention_files: int | None = None,
        time_fn: Callable[[], float] | None = None,
    ) -> None:
        self.base_path = base_path
        self.max_bytes = max_bytes
        self.retention_days = retention_days
        self.compress = compress
        # If set, number of archived .jsonl.gz files to keep (most recent)
        self.retention_files = retention_files
        self._time = time_fn or time.time
        self.base_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = _FileLock(self.base_path.with_suffix(self.base_path.suffix + ".lock"))
        self._last_day = self._now_day()
        self._part_idx = 0
        # Ensure current file exists
        self.base_path.touch(exist_ok=True)

    def _now_day(self) -> str:
        t = self._time()
        return time.strftime("%Y%m%d", time.gmtime(t))

    def _should_rotate(self) -> bool:
        try:
            st = self.base_path.stat()
            size_ok = st.st_size < self.max_bytes
        except FileNotFoundError:
            size_ok = True
        day = self._now_day()
        return (day != self._last_day) or (not size_ok)

    def _next_part_name(self) -> Path:
        ts = time.strftime("%Y%m%d.%H%M%S", time.gmtime(self._time()))
        self._part_idx += 1
        return self.base_path.with_name(f"{self.base_path.name}.{ts}.part{self._part_idx}.jsonl")

    def _gzip_and_purge(self, path: Path) -> None:
        try:
            gz = path.with_suffix(path.suffix + ".gz")
            if self.compress:
                with path.open("rb") as fin, gzip.open(gz, "wb") as fout:
                    while True:
                        chunk = fin.read(1024 * 256)
                        if not chunk:
                            break
                        fout.write(chunk)
                try:
                    path.unlink(missing_ok=True)
                except Exception:
                    pass
            else:
                # Keep plain .jsonl rotated file if compression disabled
                gz = path
        except Exception:
            pass
        # Purge old gz files
        try:
            cutoff = self._time() - self.retention_days * 86400
            # Purge by age first (if retention_days set)
            if self.retention_days is not None:
                for p in self.base_path.parent.glob(self.base_path.name + ".*.jsonl.gz"):
                    try:
                        if p.stat().st_mtime < cutoff:
                            p.unlink(missing_ok=True)
                    except Exception:
                        continue
            # Purge by count (if retention_files set): keep newest N
            if self.retention_files is not None:
                files = sorted(self.base_path.parent.glob(self.base_path.name + ".*.jsonl.gz"), key=lambda p: p.stat().st_mtime)
                # oldest first; remove until len <= retention_files
                while len(files) > self.retention_files:
                    old = files.pop(0)
                    try:
                        old.unlink(missing_ok=True)
                    except Exception:
                        pass
        except Exception:
            pass

    def write_line(self, line: str) -> None:
        # The whole write + rotate is done under a process+file lock
        with self._lock:
            try:
                if self._should_rotate():
                    # rotate current base_path
                    try:
                        roll_to = self._next_part_name()
                        if self.base_path.exists() and self.base_path.stat().st_size > 0:
                            self.base_path.rename(roll_to)
                            self._gzip_and_purge(roll_to)
                    except Exception:
                        # best-effort; reset day even if rename failed to avoid tight loop
                        pass
                    self._last_day = self._now_day()
                # append atomically
                with self.base_path.open("a", encoding="utf-8") as f:
                    f.write(line)
                    if not line.endswith("\n"):
                        f.write("\n")
                    f.flush()
                    try:
                        os.fsync(f.fileno())
                    except Exception:
                        pass
            except Exception:
                # best-effort logging only
                pass


@dataclass
class OrderLoggers:
    success_path: Path = Path(os.getenv("AURORA_SESSION_DIR", "logs")) / "orders_success.jsonl"
    failed_path: Path = Path(os.getenv("AURORA_SESSION_DIR", "logs")) / "orders_failed.jsonl"
    denied_path: Path = Path(os.getenv("AURORA_SESSION_DIR", "logs")) / "orders_denied.jsonl"
    max_bytes: int = 200 * 1024 * 1024
    retention_days: int = 7
    compress: bool = True
    retention_files: int | None = None
    _seen_cid_ts: _LRUSet = field(default_factory=lambda: _LRUSet(16384))
    _run_id: str = field(default_factory=lambda: time.strftime("%Y%m%d-%H%M%S", time.gmtime()))

    def __post_init__(self):
        self._w_success = _JsonlWriter(self.success_path, self.max_bytes, self.retention_days, compress=self.compress, retention_files=self.retention_files)
        self._w_failed = _JsonlWriter(self.failed_path, self.max_bytes, self.retention_days, compress=self.compress, retention_files=self.retention_files)
        self._w_denied = _JsonlWriter(self.denied_path, self.max_bytes, self.retention_days, compress=self.compress, retention_files=self.retention_files)

    # --- Schema mapping helpers ---
    @staticmethod
    def _to_ns(ts: Any | None) -> int:
        if ts is None:
            # now in ns
            return int(time.time() * 1_000_000_000)
        try:
            f = float(ts)
        except Exception:
            return int(time.time() * 1_000_000_000)
        # Detect unit by magnitude
        if f > 1e18:  # already ns
            return int(f)
        if f > 1e15:  # us
            return int(f * 1_000)
        if f > 1e12:  # ms
            return int(f * 1_000_000)
        if f > 1e9:  # s as float-like
            return int(f * 1_000_000_000)
        # assume seconds
        return int(f * 1_000_000_000)

    def _map_record(self, kind: str, data: dict[str, Any]) -> dict[str, Any]:
        # Input can be arbitrary kwargs from API; normalize to canonical schema
        d = dict(data)
        cid = d.get("cid") or d.get("client_order_id") or d.get("clientOrderId") or d.get("client_orderId")
        oid = d.get("oid") or d.get("order_id") or d.get("orderId") or d.get("id")
        pos_id = d.get("position_id") or d.get("positionId")
        lifecycle = (d.get("lifecycle_state") or d.get("status") or d.get("state") or "").upper() or None
        # Reasons
        reason_code = (
            d.get("reason_code")
            or d.get("deny_reason")
            or d.get("error_code")
            or None
        )
        reason_detail = d.get("reason_detail") or d.get("error_msg") or d.get("error") or None
        reason_class = d.get("reason_class")
        severity = d.get("severity")
        action = d.get("action")
        # Market context
        latency_ms = d.get("latency_ms")
        spread_bps = d.get("spread_bps")
        vol_std_bps = d.get("vol_std_bps")
        gate = d.get("governance_gate") or d.get("gate")
        reward_tag = d.get("reward_tag") or None
        ts_any = d.get("ts_ns") or d.get("ts") or d.get("timestamp")
        ts_ns = self._to_ns(ts_any)
        rec = {
            "ts_ns": int(ts_ns),
            "run_id": self._run_id,
            "cid": cid,
            "oid": oid,
            "position_id": pos_id,
            "lifecycle_state": lifecycle,
            "reason_code": reason_code,
            "reason_detail": reason_detail,
            "reason_class": reason_class,
            "severity": severity,
            "action": action,
            "latency_ms": float(latency_ms) if latency_ms is not None else None,
            "spread_bps": float(spread_bps) if spread_bps is not None else None,
            "vol_std_bps": float(vol_std_bps) if vol_std_bps is not None else None,
            "governance_gate": gate,
            "reward_tag": reward_tag,
        }
        return rec

    def _write(self, writer: _JsonlWriter, rec: dict[str, Any]) -> None:
        # Idempotency/dedup: cid + ts_ns if present
        cid = rec.get("cid")
        ts_ns = rec.get("ts_ns")
        if cid and ts_ns:
            key = (cid, ts_ns)
            if self._seen_cid_ts.contains(key):
                return
            self._seen_cid_ts.add(key)
        try:
            writer.write_line(json.dumps(rec, ensure_ascii=False))
        except Exception:
            pass

    def log_success(self, **kwargs: Any) -> None:
        rec = self._map_record("success", kwargs)
        # Legacy terminal de-dup safety on OID/STATUS still applies
        status = str(kwargs.get("status") or "").upper()
        oid = str(kwargs.get("order_id") or kwargs.get("orderId") or "")
        if status in TERMINAL_STATES and oid:
            key = ("TERM", oid, status)
            if self._seen_cid_ts.contains(key):
                return
            self._seen_cid_ts.add(key)
        self._write(self._w_success, rec)

    def log_failed(self, **kwargs: Any) -> None:
        # Normalize reason into reason_code if missing
        if kwargs.get("reason_code") is None or kwargs.get("reason_class") is None:
            n = normalize_reason_struct(kwargs.get("error_code"), kwargs.get("error_msg"))
            kwargs.setdefault("reason_code", n.get("reason_code"))
            kwargs.setdefault("reason_class", n.get("reason_class"))
            kwargs.setdefault("severity", n.get("severity"))
            kwargs.setdefault("action", n.get("action"))
        # Preserve detail field if present
        if kwargs.get("reason_detail") is None:
            kwargs["reason_detail"] = kwargs.get("error_msg")
        rec = self._map_record("failed", kwargs)
        status = str(kwargs.get("final_status") or "").upper()
        oid = str(kwargs.get("order_id") or kwargs.get("orderId") or "")
        if status in TERMINAL_STATES and oid:
            key = ("TERM", oid, status)
            if self._seen_cid_ts.contains(key):
                return
            self._seen_cid_ts.add(key)
        self._write(self._w_failed, rec)

    def log_denied(self, **kwargs: Any) -> None:
        # Prefer AURORA guard code if provided
        if kwargs.get("reason_code") is None and kwargs.get("deny_reason"):
            ar = aurora_guard_reason(str(kwargs.get("deny_reason")))
            kwargs.setdefault("reason_code", ar["reason_code"])  # type: ignore[index]
            kwargs.setdefault("reason_class", ar["reason_class"])  # type: ignore[index]
            kwargs.setdefault("severity", ar["severity"])  # type: ignore[index]
            kwargs.setdefault("action", ar["action"])  # type: ignore[index]
            kwargs.setdefault("reason_detail", ar.get("reason_detail"))  # type: ignore[call-arg]
        if kwargs.get("reason_code") is None:
            n = normalize_reason_struct(kwargs.get("error_code"), kwargs.get("error_msg"))
            kwargs.setdefault("reason_code", n["reason_code"])  # type: ignore[index]
            kwargs.setdefault("reason_class", n["reason_class"])  # type: ignore[index]
            kwargs.setdefault("severity", n["severity"])  # type: ignore[index]
            kwargs.setdefault("action", n["action"])  # type: ignore[index]
            kwargs.setdefault("reason_detail", kwargs.get("error_msg"))
        rec = self._map_record("denied", kwargs)
        self._write(self._w_denied, rec)


# Simple lifecycle resolver to be imported by other modules
def lifecycle_state_for(order_events: list[dict[str, Any]]) -> str:
    """Compute lifecycle state from a list of events for same order_id.
    Returns one of CREATED,SUBMITTED,ACK,PARTIAL,FILLED,CANCELLED,EXPIRED,UNKNOWN
    """
    priority = [
        "FILLED",
        "CANCELLED",
        "EXPIRED",
        "PARTIAL",
        "ACK",
        "SUBMITTED",
        "CREATED",
    ]
    seen = set()
    for ev in order_events:
        s = str(ev.get("status") or ev.get("state") or ev.get("lifecycle") or "").upper()
        if s:
            seen.add(s)
    for s in priority:
        if s in seen:
            return s
    return "UNKNOWN"

