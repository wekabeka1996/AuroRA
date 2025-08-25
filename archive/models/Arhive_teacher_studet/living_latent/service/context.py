from __future__ import annotations
from typing import Optional
from threading import RLock
from prometheus_client import CollectorRegistry

class ServiceContext:
    """Thread-safe holder for shared runtime objects (Acceptance, Prometheus registry, profile).
    """
    def __init__(self):
        self._lock = RLock()
        self._acceptance = None
        self._registry: Optional[CollectorRegistry] = None
        self._profile: str = "default"

    def set_acceptance(self, acc) -> None:
        with self._lock:
            self._acceptance = acc

    def get_acceptance(self):
        with self._lock:
            return self._acceptance

    def set_registry(self, reg: CollectorRegistry) -> None:
        with self._lock:
            self._registry = reg

    def get_registry(self) -> Optional[CollectorRegistry]:
        with self._lock:
            return self._registry

    def set_profile(self, profile: str) -> None:
        with self._lock:
            self._profile = profile

    def get_profile(self) -> str:
        with self._lock:
            return self._profile

CTX = ServiceContext()
