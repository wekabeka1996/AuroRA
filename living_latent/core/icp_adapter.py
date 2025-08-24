from __future__ import annotations
"""Back-compat adapter exposing legacy-like interface while delegating to AdaptiveICP.

Allows gradual migration of trading loop expecting methods similar to legacy DynamicICP
without rewriting downstream logic all at once.
"""
from typing import Any, Tuple
from .icp_dynamic import AdaptiveICP

class ICPAdapter:
    """Shim around AdaptiveICP preserving a minimal (mu, sigma)->(lo, hi) predict API."""
    def __init__(self, adaptive_icp: AdaptiveICP):
        self.icp = adaptive_icp

    def predict(self, mu: float, sigma: float, alpha: float | None = None) -> Tuple[float, float]:  # alpha ignored
        return self.icp.predict(mu, sigma)

    def update(self, y: float, mu: float, sigma: float):
        self.icp.update(y, mu, sigma)

    def stats(self) -> Any:
        return self.icp.stats()

__all__ = ["ICPAdapter"]
