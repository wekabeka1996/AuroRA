"""Certification package exports key certification components.

Heavy optional dependencies (e.g. cvxpy for DRO_ES) are imported lazily/optionally
so that light-weight metrics (CTR, ICP) can be tested without full stack.
"""

from .icp import DynamicICP  # noqa: F401
from .uncertainty import UncertaintyMetrics  # noqa: F401

try:  # pragma: no cover - optional dependency block
    # import dynamically so static analyzers don't require the optional
    # heavy dependency to be present at analysis time
    import importlib

    _mod = importlib.import_module(".dro_es", package=__package__)
    DRO_ES = getattr(_mod, "DRO_ES", None)  # type: ignore
except Exception:  # broad: any import error (cvxpy missing etc.)
    DRO_ES = None  # type: ignore
