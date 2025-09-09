from __future__ import annotations
from typing import Literal, Optional
import math

# Logistic p_fill v1 with monotonic constraints
# API:
#   p_fill_at_T(side, queue_pos, depth_at_price, obi, spread_bps, T_ms) -> float
# Normalization:
#   q = clamp(queue_pos / max(depth_at_price, eps_denom), 0, 1)
#   t = log1p(T_ms)
# Model:
#   z = b0 + b1*obi - b2*q - b3*(spread_bps/100.0) + b4*t
#   p = sigmoid(z) clipped to [eps_out, 1-eps_out]

_BETA_DEFAULTS = {"b0": -1.2, "b1": 1.8, "b2": 2.2, "b3": 0.6, "b4": 0.8}
_EPS_OUT = 1e-4
_EPS_DEN = 1e-9


def _sigmoid(x: float) -> float:
    try:
        if x >= 0:
            ex = math.exp(-x)
            return 1.0 / (1.0 + ex)
        else:
            ex = math.exp(x)
            return ex / (1.0 + ex)
    except Exception:
        # Fallback to 0.5 on extreme/overflow
        return 0.5


def _clamp(x: float, lo: float, hi: float) -> float:
    return lo if x < lo else hi if x > hi else x


def p_fill_at_T(
    side: Literal["BUY", "SELL"],
    queue_pos: float,
    depth_at_price: float,
    obi: float,
    spread_bps: int | float,
    T_ms: int | float,
    *,
    beta: Optional[dict] = None,
    eps: float = _EPS_OUT,
) -> float:
    b = beta or _BETA_DEFAULTS
    # Normalize inputs
    try:
        q_raw = float(queue_pos)
    except Exception:
        q_raw = 0.0
    try:
        depth = float(depth_at_price)
    except Exception:
        depth = 0.0
    q = q_raw / max(depth, _EPS_DEN)
    q = _clamp(q, 0.0, 1.0)
    ob = _clamp(float(obi), -1.0, 1.0)
    sp = max(0.0, float(spread_bps)) / 100.0  # bps -> percent scale per spec
    T = max(0.0, float(T_ms))
    t = math.log1p(T)

    # Logistic score
    z = float(b.get("b0", _BETA_DEFAULTS["b0"])) \
        + float(b.get("b1", _BETA_DEFAULTS["b1"])) * ob \
        - float(b.get("b2", _BETA_DEFAULTS["b2"])) * q \
        - float(b.get("b3", _BETA_DEFAULTS["b3"])) * sp \
        + float(b.get("b4", _BETA_DEFAULTS["b4"])) * t

    p = _sigmoid(z)
    eps_out = max(0.0, float(eps)) if isinstance(eps, (int, float)) else _EPS_OUT
    return _clamp(p, eps_out, 1.0 - eps_out)


# Backwards-compat thin wrapper (old signature without depth)
def p_fill_at_T_old(side: Literal["BUY", "SELL"], queue_pos: float, obi: float, spread_bps: float, T_ms: float) -> float:
    return p_fill_at_T(side, queue_pos, depth_at_price=1.0, obi=obi, spread_bps=spread_bps, T_ms=T_ms)
