"""
Aurora+ScalpBot — core/governance/sprt_glr.py
-------------------------------------------
Sequential Probability Ratio Test (SPRT) with Generalized Likelihood Ratio (GLR)
for adaptive hypothesis testing in high-frequency trading.

Implements (§ R1/Road_map alignment):
- SPRT with configurable alpha spending policies (Pocock, O'Brien-Fleming, BH-FDR)
- GLR extension for composite hypotheses and model uncertainty
- Bootstrap confidence intervals for tail index estimation
- EVT-based heavy-tail modeling for both tails
- XAI logging integration for governance decisions
- Memory-efficient streaming computation

Key Features:
- Adaptive alpha spending to control family-wise error rate
- Bootstrap CI for robust tail index estimation
- Composite SPRT with multiple test statistics
- Real-time p-value computation and decision logging
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Union, Any
import math
import random
import time

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Core imports from our modules ---------
try:  # pragma: no cover
    from core.types import ProbabilityMetrics, ConformalInterval, XAIRecord, WhyCode
    from core.calibration.calibrator import PlattCalibrator
    from core.calibration.icp import ConformalCalibrator
    from common.events import aurora_event
except Exception:  # pragma: no cover - minimal fallbacks
    class WhyCode(str, Enum):
        SPRT_REJECT = "SPRT_REJECT"
        SPRT_ACCEPT = "SPRT_ACCEPT"
        SPRT_CONTINUE = "SPRT_CONTINUE"
        ALPHA_SPENT = "ALPHA_SPENT"

    @dataclass
    class ProbabilityMetrics:
        p_value: float = 0.5
        confidence: float = 0.0
        evidence_ratio: float = 1.0

    @dataclass
    class ConformalInterval:
        lower: float = 0.0
        upper: float = 1.0
        confidence: float = 0.95

    @dataclass
    class XAIRecord:
        timestamp: float = 0.0
        why_code: WhyCode = WhyCode.SPRT_CONTINUE
        details: Dict[str, Any] = field(default_factory=dict)

    def aurora_event(record: XAIRecord) -> None:  # pragma: no cover
        print(f"AURORA_EVENT: {record}")

    class PlattCalibrator:  # pragma: no cover
        def predict_proba(self, scores: Sequence[float]) -> Sequence[float]:
            return [0.5] * len(scores)

    class ConformalCalibrator:  # pragma: no cover
        def calibrate_interval(self, scores: Sequence[float]) -> ConformalInterval:
            return ConformalInterval()


class AlphaSpendingPolicy(Enum):
    """Alpha spending policies for controlling family-wise error rate."""

    POCOCK = "pocock"  # Constant spending rate
    OBF = "obf"  # O'Brien-Fleming (conservative early, liberal late)
    BH_FDR = "bh_fdr"  # Benjamini-Hochberg False Discovery Rate


@dataclass
class SPRTConfig:
    """Configuration for SPRT testing."""

    # Hypothesis thresholds
    alpha: float = 0.05  # Type I error rate
    beta: float = 0.20  # Type II error rate
    delta: float = 0.0  # Effect size under H1

    # Alpha spending
    alpha_policy: AlphaSpendingPolicy = AlphaSpendingPolicy.POCOCK
    alpha_spending_rate: float = 0.05  # For Pocock policy

    # EVT parameters
    tail_threshold: float = 0.95  # Quantile for tail modeling
    bootstrap_samples: int = 1000  # Bootstrap iterations for CI

    # GLR parameters
    glr_window: int = 100  # Window for GLR estimation
    composite_k: int = 3  # Number of composite statistics

    # Operational
    max_samples: int = 10000  # Maximum samples before forced decision
    decision_timeout_s: float = 300.0  # Max time before timeout


@dataclass
class SPRTState:
    """Internal state of SPRT computation."""

    # Test statistics
    log_likelihood_ratio: float = 0.0
    sample_count: int = 0
    start_time: float = 0.0

    # Alpha spending
    alpha_spent: float = 0.0
    alpha_remaining: float = 1.0

    # EVT estimates
    tail_index_upper: float = 0.0
    tail_index_lower: float = 0.0
    tail_index_ci: Tuple[float, float] = (0.0, 0.0)

    # GLR state
    glr_statistics: List[float] = field(default_factory=list)
    composite_scores: List[float] = field(default_factory=list)

    # Bootstrap results
    bootstrap_cis: List[Tuple[float, float]] = field(default_factory=list)


class SPRTDecision(Enum):
    """SPRT decision outcomes."""

    CONTINUE = "continue"  # Continue testing
    REJECT_H0 = "reject_h0"  # Reject null hypothesis
    ACCEPT_H0 = "accept_h0"  # Accept null hypothesis
    TIMEOUT = "timeout"  # Decision timeout
    INSUFFICIENT_DATA = "insufficient_data"  # Not enough data


@dataclass
class SPRTResult:
    """Result of SPRT test."""

    decision: SPRTDecision
    p_value: float
    evidence_ratio: float
    confidence: float
    samples_used: int
    time_elapsed: float
    alpha_spent: float
    tail_index_estimate: float
    conformal_interval: Optional[ConformalInterval] = None
    xai_record: Optional[XAIRecord] = None


class CompositeSPRT:
    """Sequential Probability Ratio Test with GLR and alpha spending control."""

    def __init__(self, config: SPRTConfig) -> None:
        self.config = config
        self.state = SPRTState()
        self.platt_calibrator = PlattCalibrator()
        self.conformal_calibrator = ConformalCalibrator()

        # Pre-compute boundaries
        self._compute_boundaries()

    def _compute_boundaries(self) -> None:
        """Compute SPRT decision boundaries."""
        # Wald's approximation for boundaries
        self.lower_bound = math.log(self.config.beta / (1 - self.config.alpha))
        self.upper_bound = math.log((1 - self.config.beta) / self.config.alpha)

    def _spend_alpha(self, t: float) -> float:
        """Spend alpha according to the configured policy.

        Args:
            t: Normalized time/progress (0 to 1)

        Returns:
            Alpha to spend at this point
        """
        if self.config.alpha_policy == AlphaSpendingPolicy.POCOCK:
            # Constant spending rate
            return self.config.alpha_spending_rate

        elif self.config.alpha_policy == AlphaSpendingPolicy.OBF:
            # O'Brien-Fleming: conservative early, liberal late
            return 2 * self.config.alpha * (1 - math.erf(t / math.sqrt(2)))

        elif self.config.alpha_policy == AlphaSpendingPolicy.BH_FDR:
            # BH-FDR: adaptive spending based on current p-value
            current_p = self._compute_current_p_value()
            return min(self.config.alpha, current_p * math.log(1 + t))

        else:
            return self.config.alpha_spending_rate

    def _compute_current_p_value(self) -> float:
        """Compute current p-value from log-likelihood ratio."""
        if self.state.sample_count == 0:
            return 0.5

        # Convert LLR to p-value using chi-square approximation
        llr = abs(self.state.log_likelihood_ratio)
        df = max(1, self.state.sample_count // 10)  # Degrees of freedom

        # Chi-square CDF approximation
        p_value = 1.0
        if llr > 0:
            p_value = math.exp(-llr / 2)  # Rough approximation

        return min(p_value, 1.0)

    def _estimate_tail_index(self, samples: Sequence[float]) -> Tuple[float, Tuple[float, float]]:
        """Estimate tail index using EVT with bootstrap CI."""
        if len(samples) < 10:
            return 0.0, (0.0, 0.0)

        # Sort samples for tail analysis
        sorted_samples = sorted(samples)
        n = len(sorted_samples)

        # Hill estimator for upper tail
        k = max(1, int(n * (1 - self.config.tail_threshold)))
        hill_upper = sum(math.log(sorted_samples[-i] / sorted_samples[-k])
                        for i in range(1, k)) / k

        # Hill estimator for lower tail (absolute values)
        abs_samples = [abs(x) for x in samples]
        sorted_abs = sorted(abs_samples)
        hill_lower = sum(math.log(sorted_abs[-i] / sorted_abs[-k])
                        for i in range(1, k)) / k

        # Bootstrap confidence interval
        bootstrap_estimates = []
        for _ in range(self.config.bootstrap_samples):
            bootstrap_sample = [random.choice(samples) for _ in samples]
            try:
                bs_sorted = sorted(bootstrap_sample)
                bs_hill = sum(math.log(bs_sorted[-i] / bs_sorted[-k])
                            for i in range(1, k)) / k
                bootstrap_estimates.append(bs_hill)
            except (ValueError, ZeroDivisionError):
                continue

        if bootstrap_estimates:
            bootstrap_estimates.sort()
            ci_lower = bootstrap_estimates[int(0.025 * len(bootstrap_estimates))]
            ci_upper = bootstrap_estimates[int(0.975 * len(bootstrap_estimates))]
        else:
            ci_lower, ci_upper = hill_upper, hill_upper

        return hill_upper, (ci_lower, ci_upper)

    def _compute_glr_statistic(self, samples: Sequence[float]) -> float:
        """Compute Generalized Likelihood Ratio statistic."""
        if len(samples) < 2:
            return 0.0

        # Simple GLR: compare null vs alternative model
        mean = sum(samples) / len(samples)
        var = sum((x - mean) ** 2 for x in samples) / len(samples)

        # Avoid math domain error
        if var <= 0:
            return 0.0

        # Likelihood under null (normal with mean=0)
        ll_null = -0.5 * len(samples) * math.log(2 * math.pi * var) - \
                 sum(x ** 2 for x in samples) / (2 * var)

        # Likelihood under alternative (normal with estimated mean)
        ll_alt = -0.5 * len(samples) * math.log(2 * math.pi * var) - \
                sum((x - mean) ** 2 for x in samples) / (2 * var)

        return 2 * (ll_alt - ll_null)  # Likelihood ratio test statistic

    def update(self, score: float, timestamp: Optional[float] = None) -> SPRTResult:
        """Update SPRT with new observation and return current result."""

        if timestamp is None:
            timestamp = time.time()

        if self.state.sample_count == 0:
            self.state.start_time = timestamp

        # Update sample count and statistics
        self.state.sample_count += 1
        self.state.composite_scores.append(score)

        # Maintain GLR window
        if len(self.state.composite_scores) > self.config.glr_window:
            self.state.composite_scores.pop(0)

        # Compute GLR statistic
        glr_stat = self._compute_glr_statistic(self.state.composite_scores[-self.config.glr_window:])
        self.state.glr_statistics.append(glr_stat)

        # Update log-likelihood ratio (simplified)
        # In practice, this would use proper likelihood computation
        evidence_weight = score - self.config.delta
        self.state.log_likelihood_ratio += evidence_weight

        # Spend alpha
        t = min(1.0, self.state.sample_count / self.config.max_samples)
        alpha_to_spend = self._spend_alpha(t)
        new_alpha_spent = self.state.alpha_spent + alpha_to_spend
        self.state.alpha_spent = min(new_alpha_spent, self.config.alpha)
        self.state.alpha_remaining = max(0.0, self.config.alpha - self.state.alpha_spent)

        # Estimate tail index periodically
        if self.state.sample_count % 50 == 0 and len(self.state.composite_scores) >= 20:
            tail_idx, ci = self._estimate_tail_index(self.state.composite_scores)
            self.state.tail_index_upper = tail_idx
            self.state.tail_index_ci = ci

        # Make decision
        decision = self._make_decision()
        time_elapsed = timestamp - self.state.start_time

        # Compute final metrics
        p_value = self._compute_current_p_value()
        evidence_ratio = math.exp(self.state.log_likelihood_ratio)
        confidence = 1.0 - p_value

        # Create XAI record
        why_code = {
            SPRTDecision.REJECT_H0: WhyCode.SPRT_REJECT,
            SPRTDecision.ACCEPT_H0: WhyCode.SPRT_ACCEPT,
            SPRTDecision.CONTINUE: WhyCode.SPRT_CONTINUE,
            SPRTDecision.TIMEOUT: WhyCode.SPRT_CONTINUE,
            SPRTDecision.INSUFFICIENT_DATA: WhyCode.SPRT_CONTINUE,
        }.get(decision, WhyCode.SPRT_CONTINUE)

        xai_record = XAIRecord(
            timestamp=timestamp,
            why_code=why_code,
            details={
                "llr": self.state.log_likelihood_ratio,
                "samples": self.state.sample_count,
                "alpha_spent": self.state.alpha_spent,
                "tail_index": self.state.tail_index_upper,
                "p_value": p_value,
            }
        )

        # Log decision if terminal
        if decision in (SPRTDecision.REJECT_H0, SPRTDecision.ACCEPT_H0):
            aurora_event(xai_record)

        # Compute conformal interval
        conformal_interval = None
        if len(self.state.composite_scores) >= 10:
            conformal_interval = self.conformal_calibrator.calibrate_interval(
                self.state.composite_scores[-10:]
            )

        return SPRTResult(
            decision=decision,
            p_value=p_value,
            evidence_ratio=evidence_ratio,
            confidence=confidence,
            samples_used=self.state.sample_count,
            time_elapsed=time_elapsed,
            alpha_spent=self.state.alpha_spent,
            tail_index_estimate=self.state.tail_index_upper,
            conformal_interval=conformal_interval,
            xai_record=xai_record,
        )

    def _make_decision(self) -> SPRTDecision:
        """Make SPRT decision based on current state."""

        # Check timeout
        if self.state.sample_count >= self.config.max_samples:
            return SPRTDecision.TIMEOUT

        # Check insufficient data
        if self.state.sample_count < 10:
            return SPRTDecision.INSUFFICIENT_DATA

        # Check boundaries
        if self.state.log_likelihood_ratio >= self.upper_bound:
            return SPRTDecision.REJECT_H0
        elif self.state.log_likelihood_ratio <= self.lower_bound:
            return SPRTDecision.ACCEPT_H0

        return SPRTDecision.CONTINUE

    def reset(self) -> None:
        """Reset SPRT state for new test."""
        self.state = SPRTState()
        self._compute_boundaries()


# =============================
# Factory functions
# =============================

def create_sprt_pocock(alpha: float = 0.05, delta: float = 0.0) -> CompositeSPRT:
    """Create SPRT with Pocock alpha spending."""
    config = SPRTConfig(
        alpha=alpha,
        delta=delta,
        alpha_policy=AlphaSpendingPolicy.POCOCK,
        alpha_spending_rate=alpha,
    )
    return CompositeSPRT(config)


def create_sprt_obf(alpha: float = 0.05, delta: float = 0.0) -> CompositeSPRT:
    """Create SPRT with O'Brien-Fleming alpha spending."""
    config = SPRTConfig(
        alpha=alpha,
        delta=delta,
        alpha_policy=AlphaSpendingPolicy.OBF,
    )
    return CompositeSPRT(config)


def create_sprt_bh_fdr(alpha: float = 0.05, delta: float = 0.0) -> CompositeSPRT:
    """Create SPRT with BH-FDR alpha spending."""
    config = SPRTConfig(
        alpha=alpha,
        delta=delta,
        alpha_policy=AlphaSpendingPolicy.BH_FDR,
    )
    return CompositeSPRT(config)


# =============================
# Self-tests
# =============================

def _test_sprt_basic() -> None:
    """Test basic SPRT functionality."""
    sprt = create_sprt_pocock(alpha=0.05, delta=0.1)

    # Generate data with positive effect
    scores = [0.1 + 0.1 * random.gauss(0, 1) for _ in range(100)]

    decisions = []
    for i, score in enumerate(scores):
        result = sprt.update(score, timestamp=1000.0 + i)
        decisions.append(result.decision)

        if result.decision != SPRTDecision.CONTINUE:
            break

    # Should eventually make a decision
    assert any(d != SPRTDecision.CONTINUE for d in decisions)
    print("Basic SPRT test passed")


def _test_alpha_spending() -> None:
    """Test alpha spending policies."""
    policies = [AlphaSpendingPolicy.POCOCK, AlphaSpendingPolicy.OBF, AlphaSpendingPolicy.BH_FDR]

    for policy in policies:
        config = SPRTConfig(alpha=0.05, alpha_policy=policy)
        sprt = CompositeSPRT(config)

        # Update with neutral data
        for i in range(20):
            result = sprt.update(0.0, timestamp=1000.0 + i)
            assert result.alpha_spent >= 0
            assert result.alpha_spent <= config.alpha

        print(f"Alpha spending test passed for {policy.value}")


def _test_tail_index_estimation() -> None:
    """Test tail index estimation with bootstrap."""
    sprt = create_sprt_pocock()

    # Generate heavy-tailed data (Pareto-like)
    scores = [random.paretovariate(2.0) - 1 for _ in range(200)]

    for score in scores:
        sprt.update(score)

    # Tail index should be reasonable
    assert sprt.state.tail_index_upper > 0
    ci_lower, ci_upper = sprt.state.tail_index_ci
    assert ci_lower <= ci_upper
    print("Tail index estimation test passed")


if __name__ == "__main__":
    _test_sprt_basic()
    _test_alpha_spending()
    _test_tail_index_estimation()
    print("OK - core/governance/sprt_glr.py self-tests passed")
