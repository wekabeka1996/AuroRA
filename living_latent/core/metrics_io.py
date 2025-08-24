from __future__ import annotations
"""Calibration metrics derivation & objective (Batch-008 extension).

All derived metrics are clipped/normalized into [0,1] where 1 == better (unless otherwise stated),
so downstream objectives can safely bound into [-1,1].
"""
from typing import Dict
import math

# Default reference caps (can be tuned later)
_LAT_MS_CAP = 1000.0  # latency cap for normalization
_SURP_DELTA_CAP = 3.0 # surprisal delta worst reasonable bound


def _clip01(x: float) -> float:
    if math.isnan(x):
        return 0.0
    return 0.0 if x < 0 else 1.0 if x > 1 else x


def derive_calib_metrics(acc: Dict) -> Dict[str, float]:
    """Produce normalized metrics dictionary from acceptance summary record.

    Expected keys in acc (optional):
      - PASS_share / DERISK_share / BLOCK_share (or decisions_share.* in run_r0)
      - coverage_empirical, coverage_lower_bound
      - surprisal_p95 (post), surprisal_p95_pre, surprisal_p95_post
      - latency_p95_ms
      - violations_total / violations

    Fallbacks if absent.
    """
    m: Dict[str, float] = {}
    # Shares
    pass_share = acc.get('PASS_share', acc.get('decisions_share.PASS', 0.0))
    derisk_share = acc.get('DERISK_share', acc.get('decisions_share.DERISK', 0.0))
    block_share = acc.get('BLOCK_share', acc.get('decisions_share.BLOCK', 0.0))
    m['PASS_share'] = _clip01(pass_share)
    m['DERISK_share'] = _clip01(derisk_share)
    m['BLOCK_share'] = _clip01(block_share)

    # Violations
    viol = acc.get('violations', acc.get('violations_total', 0))
    # assume scaling by n external; keep raw then map to [0,1] with heuristic (>=10 saturates)
    m['violations'] = _clip01(float(viol)/10.0)

    # Surprisal delta (pre/post trigger) if provided
    surp_pre = acc.get('surprisal_p95_pre', acc.get('surprisal_p95', math.nan))
    surp_post = acc.get('surprisal_p95_post', acc.get('surprisal_p95', math.nan))
    if math.isnan(surp_pre) or math.isnan(surp_post):
        dS = 0.0
    else:
        dS = max(0.0, surp_pre - surp_post)  # improvement (drop) only
    m['dS_norm'] = _clip01(dS / _SURP_DELTA_CAP)

    # Latency normalization (lower better → invert)
    lat = float(acc.get('latency_p95_ms', acc.get('latency_p95', math.nan)))
    if math.isnan(lat):
        lat_norm = 0.0
    else:
        lat_norm = 1.0 - _clip01(lat / _LAT_MS_CAP)
    m['lat_norm'] = lat_norm

    return m


def compute_objective_v_b008_v1(m: Dict[str, float]) -> float:
    """Combine normalized metrics into objective in [-1,1].

    Heuristic linear blend (weights sum to 1 before mapping to [-1,1]):
      + w_pass * PASS_share
      + w_surp * dS_norm
      + w_lat * lat_norm
      - w_block * BLOCK_share
      - w_derisk * DERISK_share * 0.5 (less punitive than block)
      - w_viol * violations

    Result scaled into [-1,1] ensuring safe clipping.
    """
    w_pass = 0.30
    w_surp = 0.20
    w_lat = 0.20
    w_block = 0.15
    w_derisk = 0.05
    w_viol = 0.10
    score = (
        w_pass * m.get('PASS_share',0.0)
        + w_surp * m.get('dS_norm',0.0)
        + w_lat * m.get('lat_norm',0.0)
        - w_block * m.get('BLOCK_share',0.0)
        - w_derisk * m.get('DERISK_share',0.0)
        - w_viol * m.get('violations',0.0)
    )
    # Scale: weights sum to 1 ⇒ score already in [-1,1] if each term ∈ [0,1]; apply safety recenter if needed
    score = max(-1.0, min(1.0, score))
    return score

__all__ = [
    'derive_calib_metrics','compute_objective_v_b008_v1'
]
