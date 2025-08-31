from __future__ import annotations
import time
from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass
class _Entry:
    value: Any
    last_seen_ns: int


class IdempotencyStore:
    """
    In-memory TTL store. O(1) put/get/seen; O(n) sweep.
    Time source інʼєкційний для тестів.
    """
    def __init__(self, ttl_sec: int = 3600, now_ns_fn = time.time_ns):
        assert ttl_sec > 0, "ttl_sec>0"
        self._ttl_ns = int(ttl_sec * 1e9)
        self._now_ns = now_ns_fn
        self._data: Dict[str, _Entry] = {}

    def put(self, key: str, value: Any) -> None:
        self._data[key] = _Entry(value=value, last_seen_ns=self._now_ns())

    def get(self, key: str) -> Optional[Any]:
        e = self._data.get(key)
        return e.value if e else None

    def seen(self, key: str) -> bool:
        return key in self._data

    def touch(self, key: str) -> None:
        if key in self._data:
            self._data[key].last_seen_ns = self._now_ns()

    def sweep(self) -> int:
        now = self._now_ns()
        ttl = self._ttl_ns
        to_del = [k for k, e in self._data.items() if now - e.last_seen_ns > ttl]
        for k in to_del:
            del self._data[k]
        return len(to_del)
