from __future__ import annotations

from dataclasses import dataclass, field
from typing import List
from typing import Optional

from core.scalper.trap import TrapWindow, TrapMetrics
try:
    from core.calibration.icp import SplitConformalBinary
except ImportError:
    SplitConformalBinary = None


@dataclass
class PretradeReport:
    """Lightweight container for pre-trade observability.

    Attributes
    ----------
    slip_bps_est : float
        Estimated slippage in basis points for the intended order quantity.
    latency_ms : float
        Observed loop/request latency in milliseconds.
    mode_regime : str
        Market regime label (e.g., 'tight'|'normal'|'loose').
    reasons : list[str]
        Accumulated reasons for blocks/warnings.
    """

    slip_bps_est: float
    latency_ms: float
    mode_regime: str
    reasons: List[str] = field(default_factory=list)


def gate_expected_return(e_pi_bps: float, pi_min_bps: float, reasons: List[str]) -> bool:
    # TESTNET BYPASS: Завжди повертаємо True для тестування виконання
    import os
    if os.getenv('AURORA_MODE') == 'live' and os.getenv('BINANCE_ENV') == 'testnet':
        return True
    if e_pi_bps > pi_min_bps:
        return True
    reasons.append("expected_return_below_threshold")
    return False


def gate_latency(latency_ms: float, lmax_ms: float, reasons: List[str]) -> bool:
    """Latency guard: blocks if latency exceeds configured max.

    Returns True if OK (<= lmax), False otherwise and appends reason.
    """
    if latency_ms <= lmax_ms:
        return True
    reasons.append(f"latency_guard_exceeded:{latency_ms:.1f}>{lmax_ms:.1f}")
    return False


def gate_slippage(slip_bps: float, b_bps: float | None, eta_fraction_of_b: float, reasons: List[str]) -> bool:
    """Slippage guard: require slip_bps <= eta * b_bps.

    If b_bps is None or non-positive, the guard is skipped (returns True) but adds a
    diagnostic reason so callers can improve payload completeness.
    """
    if b_bps is None or b_bps <= 0:
        reasons.append("slippage_guard_skipped_no_b")
        return True
    threshold = eta_fraction_of_b * float(b_bps)
    if slip_bps <= threshold:
        return True
    reasons.append(f"slippage_guard_exceeded:{slip_bps:.2f}>{threshold:.2f}")
    return False


def gate_trap(
    tw: TrapWindow,
    cancel_deltas: List[float],
    add_deltas: List[float],
    trades_cnt: int,
    *,
    z_threshold: float,
    cancel_pctl: int,
    obi_sign: Optional[int] = None,
    tfi_sign: Optional[int] = None,
    reasons: List[str],
) -> tuple[bool, TrapMetrics]:
    """TRAP v2 gate using a rolling z-score and conflict rule.

    Returns (allow, metrics). Appends reasons if blocked.
    """
    metrics = tw.update(
        cancel_deltas=cancel_deltas,
        add_deltas=add_deltas,
        trades_cnt=trades_cnt,
        z_threshold=z_threshold,
        cancel_pctl=cancel_pctl,
        obi_sign=obi_sign,
        tfi_sign=tfi_sign,
    )
    if metrics.flag:
        reasons.append(f"trap_guard:z={metrics.trap_z:.2f}")
        return False, metrics
    return True, metrics


def gate_icp(
    iw: IcpWindow,
    price_deltas: List[float],
    trades_cnt: int,
    *,
    z_threshold: float,
    pctl: int,
    reasons: List[str],
) -> tuple[bool, IcpMetrics]:
    """ICP gate using a rolling z-score.

    Returns (allow, metrics). Appends reasons if blocked.
    """
    metrics = iw.update(
        price_deltas=price_deltas,
        trades_cnt=trades_cnt,
        z_threshold=z_threshold,
        pctl=pctl,
    )
    if metrics.flag:
        reasons.append(f"icp_guard:z={metrics.icp_z:.2f}")
        return False, metrics
    return True, metrics


def gate_icp_uncertainty(
    icp_predictor,
    features: List[float],
    reasons: List[str],
    alpha: float = 0.1
) -> bool:
    """ICP uncertainty gate: blocks if prediction set is empty (high uncertainty).
    
    Uses Inductive Conformal Prediction to assess prediction uncertainty.
    If the prediction set is empty, it indicates high uncertainty and the trade
    should be blocked.
    
    Args:
        icp_predictor: Trained SplitConformalBinary predictor
        features: Feature vector for prediction
        reasons: List to append blocking reasons
        alpha: Significance level (default 0.1 for 90% confidence)
    
    Returns:
        True if prediction set is non-empty (low uncertainty), False otherwise
    """
    if SplitConformalBinary is None:
        reasons.append("icp_guard_skipped_no_module")
        return True
    
    try:
        prediction_set = icp_predictor.predict_set(features[0])  # Use first feature as probability
        if not prediction_set:  # Empty prediction set = high uncertainty
            reasons.append(f"icp_guard_empty_prediction_set:alpha={alpha}")
            return False
        return True
    except Exception as e:
        reasons.append(f"icp_guard_error:{str(e)}")
        return True  # Allow trade if ICP fails
