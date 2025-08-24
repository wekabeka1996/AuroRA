from __future__ import annotations
import json, os, threading, time, datetime
from typing import Dict, Any, Optional

_BLACKBOX_PATH = "blackbox.jsonl"
_MAX_BYTES = 50 * 1024 * 1024  # 50 MB
_lock = threading.Lock()


def _rotate_if_needed(path: str):
    try:
        if not os.path.exists(path):
            return
        size = os.path.getsize(path)
        if size < _MAX_BYTES:
            return
        ts = datetime.datetime.utcnow().strftime("%Y%m%d_%H%M%S")
        new_name = f"{path}.{ts}"
        os.replace(path, new_name)
    except Exception:
        # rotation failure is non-fatal
        pass


def blackbox_emit(event: str, payload: Dict[str, Any], *, ts: Optional[float] = None, severity: str = "INFO") -> None:
    """Append structured event to blackbox.jsonl (thread-safe, with rotation).

    Parameters
    ----------
    event : str
        Event name.
    payload : dict
        Arbitrary JSON-serializable payload.
    ts : float, optional
        Explicit timestamp; if None uses time.time().
    severity : str
        INFO|WARN|ERROR — for downstream filtering.
    """
    record = {
        "ts": float(ts if ts is not None else time.time()),
        "event": event,
        "severity": severity,
        "payload": payload or {},
    }
    line = json.dumps(record, separators=(",", ":"), ensure_ascii=False)
    path = _BLACKBOX_PATH
    with _lock:
        _rotate_if_needed(path)
        with open(path, "a", encoding="utf-8") as f:
            f.write(line + "\n")

__all__ = ["blackbox_emit", "_BLACKBOX_PATH"]
