import math
import time
from typing import Callable, Optional
from living_latent.core.utils.blackbox import blackbox_emit

_tau_prev: Optional[float] = None
_tau_ema_abs_delta: Optional[float] = None
_tau_alpha: Optional[float] = None


def _ema_alpha_from_halflife(seconds: float) -> float:
    if not seconds or seconds <= 0:
        return 1.0
    return 1.0 - math.exp(-math.log(2.0) / float(seconds))


def set_tau_ema_halflife(halflife_s: float) -> None:
    global _tau_alpha
    _tau_alpha = _ema_alpha_from_halflife(halflife_s)


def record_tau_update(new_tau: float) -> None:
    """Record tau update and maintain EMA(|Δτ|); emit unified blackbox event."""
    global _tau_prev, _tau_ema_abs_delta, _tau_alpha
    prev = _tau_prev
    if _tau_alpha is None:
        _tau_alpha = _ema_alpha_from_halflife(3600.0)
    if prev is None:
        delta_abs = 0.0
        _tau_ema_abs_delta = delta_abs
    else:
        delta_abs = abs(new_tau - prev)
        if _tau_ema_abs_delta is None:
            _tau_ema_abs_delta = delta_abs
        else:
            _tau_ema_abs_delta = _tau_alpha * delta_abs + (1.0 - _tau_alpha) * _tau_ema_abs_delta
    _tau_prev = new_tau
    blackbox_emit("tau_drift", {"tau": new_tau, "prev": prev, "abs_delta": delta_abs, "ema": _tau_ema_abs_delta})
