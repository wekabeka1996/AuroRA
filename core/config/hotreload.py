from __future__ import annotations

"""
Hot-reload utilities for Aurora configuration system.

Provides:
- HotReloadViolation: exception on whitelist violations
- HotReloadPolicy: prefix-based allowlist for changed config keys
- diff_dicts: stable key-diff on nested dicts
- FileWatcher: simple mtime-based file watcher that triggers a callback on change

The policy intentionally uses *prefix semantics*:
  Allowed prefixes like ["risk.cvar", "execution.sla.max_latency_ms"]
  permit changes either to the key itself or any key nested under it.

This module is standalone and can be used by ConfigManager or elsewhere.
"""

import logging
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Mapping, Optional, Set, Union

logger = logging.getLogger("aurora.config.hotreload")
logger.setLevel(logging.INFO)

# -------------------- Exceptions --------------------

class HotReloadViolation(Exception):
    """Raised when a reload attempts to change non-whitelisted keys."""

# -------------------- Utilities --------------------

def _flatten(d: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, Mapping):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out


def diff_dicts(old: Mapping[str, Any], new: Mapping[str, Any]) -> Set[str]:
    """Return set of fully-qualified keys that changed between two nested mappings."""
    a = _flatten(old)
    b = _flatten(new)
    changed: Set[str] = set()
    keys = set(a.keys()).union(b.keys())
    for k in keys:
        if a.get(k) != b.get(k):
            changed.add(k)
    return changed

# -------------------- Policy --------------------

@dataclass
class HotReloadPolicy:
    whitelist: Set[str]

    @classmethod
    def from_iterable(cls, items: Iterable[str]) -> "HotReloadPolicy":
        return cls(whitelist={str(x).strip() for x in items if str(x).strip()})

    def is_allowed_key(self, key: str) -> bool:
        """
        Allowed if any whitelist entry equals key or is a prefix of key (with '.')
        """
        for w in self.whitelist:
            if key == w or key.startswith(w + "."):
                return True
        return False

    def violations(self, changed_keys: Iterable[str]) -> Set[str]:
        v: Set[str] = set()
        for k in changed_keys:
            if not self.is_allowed_key(k):
                v.add(k)
        return v

    def require(self, changed_keys: Iterable[str]) -> None:
        v = self.violations(changed_keys)
        if v:
            logger.error("Hot-reload denied; violations: %s", sorted(v))
            raise HotReloadViolation(f"Non-whitelisted changes: {sorted(v)[:5]}")

# -------------------- File watcher --------------------

class FileWatcher:
    """
    Simple mtime-based file watcher.

    on_change callback signature:  (path: Path, mtime: float) -> None
    """

    def __init__(
        self,
        path: Union[str, Path],
        on_change: Callable[[Path, float], None],
        *,
        poll_interval_sec: float = 1.5,
    ) -> None:
        self._path = Path(path).absolute()
        self._on_change = on_change
        self._poll = float(poll_interval_sec)
        self._mtime: Optional[float] = None
        self._thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()

    @property
    def path(self) -> Path:
        return self._path

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop_evt.clear()
        self._thread = threading.Thread(target=self._loop, name=f"FileWatcher[{self._path.name}]", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        if self._thread is None:
            return
        self._stop_evt.set()
        self._thread.join(timeout=3.0)
        self._thread = None

    # ----- internals -----

    def _loop(self) -> None:  # pragma: no cover (threading path)
        while not self._stop_evt.wait(self._poll):
            try:
                st = self._path.stat()
            except FileNotFoundError:
                continue
            mtime = st.st_mtime
            if self._mtime is None:
                self._mtime = mtime
                continue
            if mtime != self._mtime:
                self._mtime = mtime
                try:
                    self._on_change(self._path, mtime)
                except Exception:
                    logger.exception("FileWatcher callback failed for %s", self._path)

__all__ = [
    "HotReloadViolation",
    "HotReloadPolicy",
    "diff_dicts",
    "FileWatcher",
]
