"""Certification package exports key certification components.

Heavy optional dependencies (e.g. cvxpy for DRO_ES) are imported lazily/optionally
so that light-weight metrics (CTR, ICP) can be tested without full stack.
"""
from .icp import DynamicICP  # noqa: F401
from .uncertainty import UncertaintyMetrics  # noqa: F401

try:  # pragma: no cover - optional dependency block
	from .dro_es import DRO_ES  # noqa: F401
except Exception:  # broad: any import error (cvxpy missing etc.)
	DRO_ES = None  # type: ignore

