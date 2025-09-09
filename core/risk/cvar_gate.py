from __future__ import annotations
from decimal import Decimal


def delta_cvar_position(stop_dist_bps: int, price: Decimal, qty: Decimal) -> float:
    # Conservative: position loss at stop as proxy for tail loss contribution
    sd = Decimal(str(stop_dist_bps))
    if sd < 0:
        sd = -sd
    return float(qty * price * (sd / Decimal('10000')))


def allow_trade(port_cvar_curr: float, delta_cvar: float, limit: float) -> bool:
    return (port_cvar_curr + max(0.0, float(delta_cvar))) <= float(limit)
