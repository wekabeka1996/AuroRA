from __future__ import annotations
from typing import Callable, Dict

try:  # pragma: no cover
    from prometheus_client import Gauge
except Exception:  # pragma: no cover
    class Gauge:  # type: ignore
        def __init__(self, *a, **kw): pass
        def labels(self, *a, **kw): return self
        def set(self, *a, **kw): return None

_registry: Dict[str, Gauge] = {}

def gauge(name: str, doc: str) -> Callable[[float], None]:
    if name not in _registry:
        _registry[name] = Gauge(name, doc, [])
    g = _registry[name]
    def _set(v: float):
        try:
            g.set(float(v))
        except Exception:
            pass
    return _set

# DRO specific setters (used in dro_es_optimize already)
_dro_obj_g = gauge("aurora_dro_objective", "DRO-ES objective")
_dro_rt_g = gauge("aurora_dro_runtime_ms", "DRO-ES runtime")
_dro_pen_g = gauge("aurora_dro_penalty", "DRO penalty (objective component)")

def set_dro_objective(v: float):
    _dro_obj_g(float(v))

def set_dro_runtime_ms(v: float):
    _dro_rt_g(float(v))

def set_dro_penalty(v: float):
    _dro_pen_g(float(v))
__all__ = ["gauge", "set_dro_objective", "set_dro_runtime_ms", "set_dro_penalty"]
