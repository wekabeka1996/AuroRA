"""
Aurora+ScalpBot — repo/core/sizing/kelly.py
==========================================

Kelly sizing primitives for single-asset and portfolio settings.
Implements the specified API contracts for Step 2: Sizing/Portfolio.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Any, Tuple, List
import math
import time

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore


def kelly_binary(
    p_win: float,
    rr: float,
    risk_aversion: float = 1.0,
    clip: Tuple[float, float] = (0.0, 0.2)
) -> float:
    """
    Kelly fraction for binary outcome with risk aversion and clipping.

    Parameters
    ----------
    p_win : float
        Probability of winning (0 <= p_win <= 1)
    rr : float
        Reward-to-risk ratio (G/L where G=gain, L=loss)
    risk_aversion : float
        Risk aversion multiplier (higher = more conservative)
    clip : tuple
        (min_fraction, max_fraction) bounds

    Returns
    -------
    float
        Kelly fraction f* (0 <= f* <= clip[1])

    Notes
    -----
    Formula: f* = (b*p - (1-p)) / b where b = rr
    With risk aversion: f = f* / risk_aversion
    Clipped to [clip[0], clip[1]]
    """
    try:
        p_win = float(p_win)
        rr = float(rr)
        risk_aversion = float(risk_aversion)
        clip_min, clip_max = float(clip[0]), float(clip[1])
    except Exception:
        return 0.0

    # Input validation
    if not (0.0 <= p_win <= 1.0) or rr <= 0.0 or risk_aversion <= 0.0:
        return 0.0
    if clip_min < 0.0 or clip_max < clip_min:
        return 0.0

    # Classic Kelly formula
    b = rr  # reward/risk ratio
    f_star = (b * p_win - (1.0 - p_win)) / b

    # Apply risk aversion
    f = f_star / risk_aversion

    # Clip to bounds
    f = max(clip_min, min(f, clip_max))

    # Safety checks
    if math.isnan(f) or math.isinf(f):
        return 0.0

    return f


def kelly_mu_sigma(
    mu: float,
    sigma: float,
    risk_aversion: float = 1.0,
    clip: Tuple[float, float] = (0.0, 0.2)
) -> float:
    """
    Kelly fraction using mean-variance approximation.

    Parameters
    ----------
    mu : float
        Expected return (can be negative)
    sigma : float
        Return volatility (must be > 0)
    risk_aversion : float
        Risk aversion multiplier
    clip : tuple
        (min_fraction, max_fraction) bounds

    Returns
    -------
    float
        Kelly fraction f = (mu / sigma²) / risk_aversion, clipped

    Notes
    -----
    For continuous returns: f = μ / σ²
    This is the continuous-time analog of binary Kelly.
    """
    try:
        mu = float(mu)
        sigma = float(sigma)
        risk_aversion = float(risk_aversion)
        clip_min, clip_max = float(clip[0]), float(clip[1])
    except Exception:
        return 0.0

    # Input validation
    if sigma <= 0.0 or risk_aversion <= 0.0:
        return 0.0
    if clip_min < 0.0 or clip_max < clip_min:
        return 0.0

    # Mean-variance Kelly
    f = (mu / (sigma ** 2)) / risk_aversion

    # Clip to bounds
    f = max(clip_min, min(f, clip_max))

    # Safety checks
    if math.isnan(f) or math.isinf(f):
        return 0.0

    return f


def fraction_to_qty(
    notional_usd: float,
    px: float,
    lot_step: float,
    min_notional: float,
    max_notional: float,
    leverage: float = 1.0,
    initial_margin_pct: float = 0.1,
    maintenance_margin_pct: float = 0.05,
    price_step: Optional[float] = None
) -> float:
    """
    Convert Kelly fraction to executable quantity with exchange constraints.

    Parameters
    ----------
    notional_usd : float
        Target notional value in USD
    px : float
        Asset price
    lot_step : float
        Minimum quantity increment (e.g., 0.00001 for BTC)
    min_notional : float
        Exchange minimum notional
    max_notional : float
        Exchange maximum notional
    leverage : float
        Leverage multiplier (default 1.0 for spot)
    initial_margin_pct : float
        Initial margin percentage (for futures)
    maintenance_margin_pct : float
        Maintenance margin percentage (for futures)
    price_step : float, optional
        Minimum price increment (for price rounding)

    Returns
    -------
    float
        Executable quantity, or 0.0 if constraints violated

    Notes
    -----
    Rounds quantity to nearest lot_step, then validates notional bounds.
    For futures: accounts for leverage and margin requirements.
    """
    try:
        notional_usd = float(notional_usd)
        px = float(px)
        lot_step = float(lot_step)
        min_notional = float(min_notional)
        max_notional = float(max_notional)
        leverage = float(leverage)
        initial_margin_pct = float(initial_margin_pct)
        maintenance_margin_pct = float(maintenance_margin_pct)
        if price_step is not None:
            price_step = float(price_step)
    except Exception:
        return 0.0

    # Input validation
    if (notional_usd <= 0.0 or px <= 0.0 or lot_step <= 0.0 or
        leverage <= 0.0 or initial_margin_pct <= 0.0 or maintenance_margin_pct <= 0.0):
        return 0.0
    if min_notional < 0.0 or max_notional < min_notional:
        return 0.0

    # Skip tiny positions (less than 0.1% of equity)
    if notional_usd < 10.0:  # Very small notional
        return 0.0

    # For futures: adjust for leverage and margin requirements
    if leverage > 1.0:
        # Required margin for the position
        required_margin = notional_usd / leverage
        
        # Check if we have sufficient margin
        available_margin = notional_usd * initial_margin_pct
        if required_margin > available_margin:
            return 0.0  # Insufficient margin

    # Calculate base quantity
    qty = notional_usd / px

    # Round to lot step
    if lot_step > 0.0:
        qty = round(qty / lot_step) * lot_step

    # Skip if quantity is too small to be meaningful
    if qty < lot_step:
        return 0.0

    # Validate notional bounds
    actual_notional = qty * px
    if actual_notional < min_notional or actual_notional > max_notional:
        return 0.0

    # Final safety check
    if qty <= 0.0 or math.isnan(qty) or math.isinf(qty):
        return 0.0

    return qty


def edge_to_pwin(
    edge_bps: float,
    rr: float = 1.0
) -> float:
    """
    Convert edge estimate to win probability for Kelly sizing.

    Parameters
    ----------
    edge_bps : float
        Expected edge in basis points
    rr : float
        Reward-to-risk ratio (default 1.0 for symmetric bets)

    Returns
    -------
    float
        Implied win probability p_win ∈ [0, 1]

    Notes
    -----
    For binary bet: E[R] = p_win * rr - (1-p_win) * 1
    Solving: p_win = (E[R] + 1) / (1 + rr)
    Where E[R] = edge_bps / 10000 (convert bps to fraction)
    """
    try:
        edge_bps = float(edge_bps)
        rr = float(rr)
    except Exception:
        return 0.5  # Neutral probability on error

    # Input validation
    if rr <= 0.0:
        return 0.5

    # Convert edge to expected return fraction
    expected_return = edge_bps / 10000.0

    # Solve for p_win
    if rr == 1.0:
        # Symmetric case: p_win = (E[R] + 1) / 2
        p_win = (expected_return + 1.0) / 2.0
    else:
        # General case: p_win = (E[R] + 1) / (1 + rr)
        p_win = (expected_return + 1.0) / (1.0 + rr)

    # Clip to valid probability range
    p_win = max(0.0, min(1.0, p_win))

    # Safety checks
    if math.isnan(p_win) or math.isinf(p_win):
        return 0.5

    return p_win


def dd_haircut_factor(current_dd_bps: float, dd_max_bps: float = 300.0, beta: float = 2.0) -> float:
    """
    Calculate DD haircut factor for Kelly sizing.

    Implements g(D) = max(0, 1 - (D/DD_max))^β where:
    - D is current drawdown in bps
    - DD_max is maximum allowed drawdown in bps
    - β controls the haircut steepness (typically 2.0)

    Parameters
    ----------
    current_dd_bps : float
        Current drawdown in basis points
    dd_max_bps : float
        Maximum allowed drawdown in basis points
    beta : float
        Haircut steepness parameter

    Returns
    -------
    float
        Haircut factor ∈ [0, 1], where 1 = no haircut, 0 = full haircut

    Notes
    -----
    As drawdown increases, the haircut factor decreases strictly,
    reducing position sizes to protect capital during losses.
    """
    try:
        current_dd_bps = float(current_dd_bps)
        dd_max_bps = float(dd_max_bps)
        beta = float(beta)
    except Exception:
        return 1.0

    # Input validation
    if dd_max_bps <= 0.0 or beta <= 0.0:
        return 1.0

    # Calculate normalized drawdown
    d_norm = current_dd_bps / dd_max_bps

    # Apply haircut formula
    if d_norm >= 1.0:
        return 0.0  # Full haircut when DD exceeds limit
    elif d_norm <= 0.0:
        return 1.0  # No haircut when no DD
    else:
        haircut = 1.0 - d_norm
        return max(0.0, haircut ** beta)


def apply_dd_haircut_to_kelly(
    kelly_fraction: float,
    current_dd_bps: float,
    dd_max_bps: float = 300.0,
    beta: float = 2.0
) -> float:
    """
    Apply DD haircut to Kelly fraction.

    Parameters
    ----------
    kelly_fraction : float
        Raw Kelly fraction
    current_dd_bps : float
        Current drawdown in basis points
    dd_max_bps : float
        Maximum allowed drawdown in basis points
    beta : float
        Haircut steepness parameter

    Returns
    -------
    float
        Haircut-adjusted Kelly fraction
    """
    haircut = dd_haircut_factor(current_dd_bps, dd_max_bps, beta)
    return kelly_fraction * haircut


# Legacy compatibility - keep existing functions
def raw_kelly_fraction(p: float, G: float, L: float, f_max: float = 1.0) -> float:
    """Legacy function - use kelly_binary instead."""
    if L <= 0.0 or G <= 0.0:
        return 0.0
    rr = G / L
    # Legacy behavior: no risk aversion, just direct Kelly with clipping
    f_star = (rr * p - (1.0 - p)) / rr
    return max(0.0, min(f_star, f_max))


@dataclass
class KellyOrchestrator:
    """Legacy class - kept for compatibility."""
    cap: float = 1.0

    def lambda_product(self, lambdas: Optional[Dict[str, float]]) -> float:
        if not lambdas:
            return 1.0
        prod = 1.0
        for k, v in lambdas.items():
            try:
                x = float(v)
            except Exception:
                x = 1.0
            x = max(0.0, min(1.0, x))
            prod *= x
        return max(0.0, min(1.0, prod))

    def size(self, p: float, G: float, L: float, *, lambdas: Optional[Dict[str, float]] = None, f_max: Optional[float] = None) -> float:
        f_raw = raw_kelly_fraction(p, G, L, f_max=self.cap if f_max is None else min(self.cap, float(f_max)))
        mult = self.lambda_product(lambdas)
        f_star = f_raw * mult
        return max(0.0, min(self.cap, f_star))


# Portfolio Kelly (legacy - use PortfolioOptimizer instead)
def portfolio_kelly(
    mu: list[float],
    Sigma: list[list[float]],
    *,
    ridge: float = 1e-6,
    leverage_cap: float = 1.0,
    long_only: bool = False,
) -> list[float]:
    """Legacy function - use PortfolioOptimizer instead."""
    if np is None:
        # Fallback implementation
        n = len(mu)
        if n == 0:
            return []

        # Simple equal weight fallback
        w = [1.0 / n] * n

        # Apply leverage cap
        lev = sum(abs(wi) for wi in w)
        if lev > leverage_cap:
            scale = leverage_cap / lev
            w = [wi * scale for wi in w]

        return w

    # NumPy implementation
    A = np.array(Sigma, dtype=float)
    A = A + np.eye(len(mu)) * ridge
    b = np.array(mu, dtype=float)

    try:
        w = np.linalg.solve(A, b)
    except Exception:
        w = np.linalg.pinv(A).dot(b)

    w_list = [float(x) for x in w.tolist()]

    # Long-only projection
    if long_only:
        w_list = [max(0.0, wi) for wi in w_list]

    # Leverage scaling
    lev = sum(abs(wi) for wi in w_list)
    cap = max(1e-12, float(leverage_cap))
    if lev > cap:
        scale = cap / lev
        w_list = [wi * scale for wi in w_list]

    return w_list


@dataclass
class SizingStabilizer:
    """
    Sizing stabilizer with hysteresis, time guards, and bucket sizing.

    Prevents excessive position changes and provides stability controls.
    """

    # Hysteresis parameters
    hysteresis_threshold: float = 0.1  # τ = 0.1 * current_f
    hysteresis_flip_threshold: float = 0.2  # τ_flip = 0.2 * current_f

    # Time guard parameters
    min_resize_interval_sec: float = 5.0  # Minimum time between resizes
    last_resize_time: float = 0.0

    # Bucket sizing parameters
    bucket_sizes: Optional[List[float]] = None  # Discrete position sizes

    def __post_init__(self):
        if self.bucket_sizes is None:
            # Default bucket sizes: 0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0
            self.bucket_sizes = [0.0, 0.01, 0.02, 0.05, 0.1, 0.2, 0.5, 1.0]

    def apply_hysteresis(
        self,
        target_fraction: float,
        current_fraction: float
    ) -> float:
        """
        Apply hysteresis to prevent small oscillations.

        Parameters
        ----------
        target_fraction : float
            New target Kelly fraction
        current_fraction : float
            Current position fraction

        Returns
        -------
        float
            Stabilized fraction (may keep current if change too small)
        """
        if current_fraction == 0.0:
            # No current position - allow any positive target
            return target_fraction

        # Calculate dynamic thresholds
        tau = self.hysteresis_threshold * abs(current_fraction)
        tau_flip = self.hysteresis_flip_threshold * abs(current_fraction)

        # Calculate change
        delta = target_fraction - current_fraction
        abs_delta = abs(delta)

        # Apply hysteresis logic
        if abs_delta < tau:
            # Change too small - keep current
            return current_fraction
        elif abs(target_fraction) < tau_flip and abs(current_fraction) >= tau_flip:
            # Target near zero but current significant - require larger change to flip
            if abs_delta < tau_flip:
                return current_fraction

        return target_fraction

    def check_time_guard(self) -> bool:
        """
        Check if enough time has passed since last resize.

        Returns
        -------
        bool
            True if resize is allowed, False if too soon
        """
        current_time = time.time()
        time_since_last = current_time - self.last_resize_time

        return time_since_last >= self.min_resize_interval_sec

    def apply_bucket_sizing(self, target_fraction: float) -> float:
        """
        Apply bucket sizing to use discrete position sizes.

        Parameters
        ----------
        target_fraction : float
            Target Kelly fraction

        Returns
        -------
        float
            Nearest bucket size
        """
        if not self.bucket_sizes:
            return target_fraction

        # Find closest bucket size
        closest_bucket = min(self.bucket_sizes, key=lambda x: abs(x - target_fraction))

        return closest_bucket

    def stabilize_fraction(
        self,
        target_fraction: float,
        current_fraction: float = 0.0,
        apply_hysteresis: bool = True,
        apply_time_guard: bool = True,
        apply_bucket: bool = True
    ) -> tuple[float, dict]:
        """
        Apply all stabilization features to target fraction.

        Parameters
        ----------
        target_fraction : float
            Raw target Kelly fraction
        current_fraction : float
            Current position fraction
        apply_hysteresis : bool
            Whether to apply hysteresis
        apply_time_guard : bool
            Whether to check time guard
        apply_bucket : bool
            Whether to apply bucket sizing

        Returns
        -------
        tuple[float, dict]
            (stabilized_fraction, metadata_dict)
        """
        metadata = {
            "original_target": target_fraction,
            "current_fraction": current_fraction,
            "time_guard_passed": True,
            "hysteresis_applied": False,
            "bucket_applied": False,
            "final_fraction": target_fraction
        }

        # Start with target
        stabilized = target_fraction

        # Apply time guard
        if apply_time_guard:
            metadata["time_guard_passed"] = self.check_time_guard()
            if not metadata["time_guard_passed"]:
                stabilized = current_fraction
                metadata["final_fraction"] = stabilized
                return stabilized, metadata

        # Apply hysteresis
        if apply_hysteresis:
            hysteresis_result = self.apply_hysteresis(stabilized, current_fraction)
            if hysteresis_result != stabilized:
                metadata["hysteresis_applied"] = True
            stabilized = hysteresis_result

        # Apply bucket sizing
        if apply_bucket:
            bucket_result = self.apply_bucket_sizing(stabilized)
            if bucket_result != stabilized:
                metadata["bucket_applied"] = True
            stabilized = bucket_result

        # Update last resize time if actually changed
        if stabilized != current_fraction:
            self.last_resize_time = time.time()

        metadata["final_fraction"] = stabilized
        return stabilized, metadata



__all__ = [
    "kelly_binary",
    "kelly_mu_sigma",
    "fraction_to_qty",
    "edge_to_pwin",
    "dd_haircut_factor",
    "apply_dd_haircut_to_kelly",
    "SizingStabilizer",
    "raw_kelly_fraction",
    "KellyOrchestrator",
    "portfolio_kelly"
]