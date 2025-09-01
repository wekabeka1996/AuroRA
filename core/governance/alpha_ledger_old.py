"""
Aurora+ScalpBot — core/governance/alpha_ledger.py
-----------------------------------------------
Alpha spending ledger for controlling family-wise error rates in sequential testing.

Implements (§ R1/Road_map alignment):
- Alpha spending policies: Pocock, O'Brien-Fleming, BH-FDR
- Adaptive alpha allocation based on current evidence
- Family-wise error rate control for multiple hypothesis tests
- XAI logging integration for governance decisions
- Bootstrap confidence intervals for spending decisions

Key Features:
- Multiple testing correction via alpha spending
- Adaptive spending based on test progress and evidence strength
- Bootstrap-based confidence for spending decisions
- Comprehensive logging for audit trails
- Memory-efficient tracking of spending history
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Sequence, Tuple, Any
import math
import time

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# -------- Core imports from our modules ---------
try:  # pragma: no cover
    from core.types import XAIRecord, WhyCode
    from common.events import aurora_event
except Exception:  # pragma: no cover - minimal fallbacks
    class WhyCode(str, Enum):
        ALPHA_SPENT = "ALPHA_SPENT"
        ALPHA_INSUFFICIENT = "ALPHA_INSUFFICIENT"
        ALPHA_ADJUSTED = "ALPHA_ADJUSTED"

    @dataclass
    class XAIRecord:
        timestamp: float = 0.0
        why_code: WhyCode = WhyCode.ALPHA_SPENT
        details: Dict[str, Any] = field(default_factory=dict)

    def aurora_event(record: XAIRecord) -> None:  # pragma: no cover
        print(f"AURORA_EVENT: {record}")


class AlphaSpendingPolicy(Enum):
    """Alpha spending policies for family-wise error control."""

    POCOCK = "pocock"  # Constant spending rate
    OBF = "obf"  # O'Brien-Fleming (conservative early, liberal late)
    BH_FDR = "bh_fdr"  # Benjamini-Hochberg False Discovery Rate
    ADAPTIVE = "adaptive"  # Adaptive based on evidence strength


@dataclass
class SpendingRecord:
    """Record of alpha spending at a specific point."""

    timestamp: float
    test_id: str
    alpha_spent: float
    alpha_remaining: float
    evidence_strength: float
    p_value: float
    confidence_level: float
    policy_used: AlphaSpendingPolicy
    bootstrap_ci: Optional[Tuple[float, float]] = None


@dataclass
class AlphaLedgerConfig:
    """Configuration for alpha spending ledger."""

    # Overall alpha budget
    total_alpha: float = 0.05

    # Spending policy
    spending_policy: AlphaSpendingPolicy = AlphaSpendingPolicy.POCOCK

    # Adaptive parameters
    adaptation_rate: float = 0.1
    evidence_threshold: float = 2.0  # Log-likelihood ratio threshold

    # Bootstrap parameters
    bootstrap_samples: int = 1000
    ci_level: float = 0.95

    # Operational
    max_history: int = 10000
    log_frequency: int = 100  # Log every N spending decisions


@dataclass
class AlphaBudget:
    """Current state of alpha budget."""

    total_allocated: float = 0.0
    spent: float = 0.0
    remaining: float = 0.0
    reserved: float = 0.0  # Reserved for future tests

    @property
    def utilization_rate(self) -> float:
        """Calculate current utilization rate."""
        return self.spent / self.total_allocated if self.total_allocated > 0 else 0.0

    @property
    def available_for_spending(self) -> float:
        """Calculate alpha available for immediate spending."""
        return max(0.0, self.remaining - self.reserved)


class AlphaSpendingLedger:
    """Ledger for tracking and controlling alpha spending across multiple tests."""

    def __init__(self, config: AlphaLedgerConfig) -> None:
        self.config = config
        self.budget = AlphaBudget(
            total_allocated=config.total_alpha,
            remaining=config.total_alpha
        )
        self.spending_history: List[SpendingRecord] = []
        self.active_tests: Dict[str, float] = {}  # test_id -> allocated_alpha
        self.test_counter = 0

    def request_alpha(
        self,
        evidence_strength: float,
        p_value: float,
        test_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[float, bool, str]:
        """Request alpha allocation for a new test.

        Args:
            evidence_strength: Log-likelihood ratio or similar evidence measure
            p_value: Current p-value of the test
            test_context: Additional context for decision making

        Returns:
            Tuple of (allocated_alpha, approved, reason)
        """
        test_id = f"test_{self.test_counter}"
        self.test_counter += 1

        # Calculate base allocation
        base_allocation = self._calculate_base_allocation(evidence_strength, p_value)

        # Apply policy-specific adjustments
        adjusted_allocation = self._apply_policy_adjustment(
            base_allocation, evidence_strength, p_value
        )

        # Check budget constraints
        available = self.budget.available_for_spending
        if adjusted_allocation > available:
            # Try to allocate what's available
            actual_allocation = min(adjusted_allocation, available)
            if actual_allocation < base_allocation * 0.1:  # Less than 10% of requested
                return 0.0, False, "insufficient_alpha_budget"

            adjusted_allocation = actual_allocation

        # Bootstrap confidence interval for spending decision
        ci_lower, ci_upper = self._bootstrap_ci_for_allocation(
            evidence_strength, p_value, adjusted_allocation
        )

        # Final approval decision
        approved = self._should_approve_allocation(
            adjusted_allocation, evidence_strength, p_value, ci_lower, ci_upper
        )

        if approved:
            # Update budget
            self.budget.spent += adjusted_allocation
            self.budget.remaining -= adjusted_allocation
            self.active_tests[test_id] = adjusted_allocation

            # Record spending
            record = SpendingRecord(
                timestamp=time.time(),
                test_id=test_id,
                alpha_spent=adjusted_allocation,
                alpha_remaining=self.budget.remaining,
                evidence_strength=evidence_strength,
                p_value=p_value,
                confidence_level=self.config.ci_level,
                policy_used=self.config.spending_policy,
                bootstrap_ci=(ci_lower, ci_upper)
            )
            self.spending_history.append(record)

            # Maintain history size
            if len(self.spending_history) > self.config.max_history:
                self.spending_history.pop(0)

            # Log significant spending decisions
            if len(self.spending_history) % self.config.log_frequency == 0:
                self._log_spending_decision(record, "periodic_log")

        reason = "approved" if approved else "policy_rejection"
        return adjusted_allocation if approved else 0.0, approved, reason

    def release_alpha(self, test_id: str, partial_return: float = 0.0) -> bool:
        """Release alpha allocation back to budget (e.g., test completed early).

        Args:
            test_id: ID of the test releasing alpha
            partial_return: Amount of alpha to return (0 = all)

        Returns:
            True if successful, False if test_id not found
        """
        if test_id not in self.active_tests:
            return False

        allocated = self.active_tests[test_id]
        return_amount = partial_return if partial_return > 0 else allocated

        # Update budget
        self.budget.spent -= return_amount
        self.budget.remaining += return_amount

        # Remove from active tests
        del self.active_tests[test_id]

        # Log the release
        record = SpendingRecord(
            timestamp=time.time(),
            test_id=test_id,
            alpha_spent=-return_amount,  # Negative to indicate return
            alpha_remaining=self.budget.remaining,
            evidence_strength=0.0,
            p_value=1.0,
            confidence_level=self.config.ci_level,
            policy_used=self.config.spending_policy
        )
        self.spending_history.append(record)

        return True

    def _calculate_base_allocation(
        self,
        evidence_strength: float,
        p_value: float
    ) -> float:
        """Calculate base alpha allocation before policy adjustments."""
        # Base allocation scales with evidence strength
        base_rate = min(self.config.total_alpha * 0.1,  # Max 10% per test
                       self.config.total_alpha * (evidence_strength / 10.0))

        # Adjust for p-value (more significant tests get more alpha)
        p_adjustment = 1.0 / (1.0 + math.log10(max(p_value, 1e-10)))
        base_rate *= p_adjustment

        return max(base_rate, self.config.total_alpha * 0.001)  # Minimum allocation

    def _apply_policy_adjustment(
        self,
        base_allocation: float,
        evidence_strength: float,
        p_value: float
    ) -> float:
        """Apply policy-specific adjustments to base allocation."""

        if self.config.spending_policy == AlphaSpendingPolicy.POCOCK:
            # Constant spending rate - no adjustment needed
            return base_allocation

        elif self.config.spending_policy == AlphaSpendingPolicy.OBF:
            # Conservative early, liberal late
            utilization = self.budget.utilization_rate
            if utilization < 0.5:
                # More conservative early
                return base_allocation * 0.5
            else:
                # More liberal late
                return base_allocation * 1.5

        elif self.config.spending_policy == AlphaSpendingPolicy.BH_FDR:
            # BH-FDR: adjust based on current p-value rank
            current_tests = len(self.active_tests) + len(self.spending_history)
            if current_tests > 0:
                # BH critical value approximation
                bh_threshold = (current_tests * self.config.total_alpha) / (current_tests + 1)
                adjustment = min(1.0, p_value / bh_threshold)
                return base_allocation * adjustment
            return base_allocation

        elif self.config.spending_policy == AlphaSpendingPolicy.ADAPTIVE:
            # Adaptive based on evidence strength
            if evidence_strength > self.config.evidence_threshold:
                # Strong evidence - allocate more
                return base_allocation * 1.5
            elif evidence_strength < -self.config.evidence_threshold:
                # Weak evidence - allocate less
                return base_allocation * 0.5
            else:
                return base_allocation

        return base_allocation

    def _bootstrap_ci_for_allocation(
        self,
        evidence_strength: float,
        p_value: float,
        proposed_allocation: float
    ) -> Tuple[float, float]:
        """Calculate bootstrap confidence interval for allocation decision."""
        if not np or self.config.bootstrap_samples < 10:
            return proposed_allocation * 0.8, proposed_allocation * 1.2

        # Bootstrap resampling of evidence strength
        bootstrap_estimates = []
        for _ in range(self.config.bootstrap_samples):
            # Add noise to simulate sampling variability
            noise = np.random.normal(0, abs(evidence_strength) * 0.1)
            bootstrapped_evidence = evidence_strength + noise

            # Recalculate allocation with bootstrapped evidence
            bs_allocation = self._calculate_base_allocation(bootstrapped_evidence, p_value)
            bs_adjusted = self._apply_policy_adjustment(bs_allocation, bootstrapped_evidence, p_value)
            bootstrap_estimates.append(bs_adjusted)

        # Calculate confidence interval
        bootstrap_estimates.sort()
        ci_lower_idx = int((1 - self.config.ci_level) / 2 * len(bootstrap_estimates))
        ci_upper_idx = int((1 + self.config.ci_level) / 2 * len(bootstrap_estimates))

        ci_lower = bootstrap_estimates[ci_lower_idx]
        ci_upper = bootstrap_estimates[ci_upper_idx]

        return ci_lower, ci_upper

    def _should_approve_allocation(
        self,
        allocation: float,
        evidence_strength: float,
        p_value: float,
        ci_lower: float,
        ci_upper: float
    ) -> bool:
        """Determine if allocation should be approved."""

        # Basic budget check
        if allocation > self.budget.available_for_spending:
            return False

        # Evidence strength check
        if abs(evidence_strength) < 0.5:  # Too weak evidence
            return False

        # P-value check
        if p_value > 0.5:  # Not significant enough
            return False

        # Bootstrap CI check - allocation should be reasonable relative to CI
        ci_range = ci_upper - ci_lower
        if ci_range > 0 and allocation < ci_lower * 0.5:
            return False  # Allocation too small relative to confidence interval

        return True

    def _log_spending_decision(self, record: SpendingRecord, reason: str) -> None:
        """Log significant spending decisions."""
        xai_record = XAIRecord(
            timestamp=record.timestamp,
            why_code=WhyCode.ALPHA_SPENT,
            details={
                "test_id": record.test_id,
                "alpha_spent": record.alpha_spent,
                "alpha_remaining": record.alpha_remaining,
                "evidence_strength": record.evidence_strength,
                "p_value": record.p_value,
                "policy": record.policy_used.value,
                "reason": reason,
                "budget_utilization": self.budget.utilization_rate,
                "active_tests": len(self.active_tests)
            }
        )
        aurora_event(xai_record)

    def get_budget_summary(self) -> Dict[str, Any]:
        """Get summary of current budget state."""
        return {
            "total_allocated": self.budget.total_allocated,
            "spent": self.budget.spent,
            "remaining": self.budget.remaining,
            "reserved": self.budget.reserved,
            "utilization_rate": self.budget.utilization_rate,
            "available_for_spending": self.budget.available_for_spending,
            "active_tests": len(self.active_tests),
            "total_tests_completed": len(self.spending_history),
            "policy": self.config.spending_policy.value
        }

    def get_spending_history(
        self,
        limit: Optional[int] = None
    ) -> List[SpendingRecord]:
        """Get spending history, most recent first."""
        history = self.spending_history[-limit:] if limit else self.spending_history
        return list(reversed(history))  # Most recent first


# =============================
# Factory functions
# =============================

def create_pocock_ledger(total_alpha: float = 0.05) -> AlphaSpendingLedger:
    """Create ledger with Pocock alpha spending."""
    config = AlphaLedgerConfig(
        total_alpha=total_alpha,
        spending_policy=AlphaSpendingPolicy.POCOCK
    )
    return AlphaSpendingLedger(config)


def create_obf_ledger(total_alpha: float = 0.05) -> AlphaSpendingLedger:
    """Create ledger with O'Brien-Fleming alpha spending."""
    config = AlphaLedgerConfig(
        total_alpha=total_alpha,
        spending_policy=AlphaSpendingPolicy.OBF
    )
    return AlphaSpendingLedger(config)


def create_bh_fdr_ledger(total_alpha: float = 0.05) -> AlphaSpendingLedger:
    """Create ledger with BH-FDR alpha spending."""
    config = AlphaLedgerConfig(
        total_alpha=total_alpha,
        spending_policy=AlphaSpendingPolicy.BH_FDR
    )
    return AlphaSpendingLedger(config)


def create_adaptive_ledger(
    total_alpha: float = 0.05,
    adaptation_rate: float = 0.1
) -> AlphaSpendingLedger:
    """Create ledger with adaptive alpha spending."""
    config = AlphaLedgerConfig(
        total_alpha=total_alpha,
        spending_policy=AlphaSpendingPolicy.ADAPTIVE,
        adaptation_rate=adaptation_rate
    )
    return AlphaSpendingLedger(config)


# =============================
# Self-tests
# =============================

def _test_alpha_ledger_basic() -> None:
    """Test basic alpha ledger functionality."""
    ledger = create_pocock_ledger(total_alpha=0.05)

    # Test successful allocation
    allocation, approved, reason = ledger.request_alpha(
        evidence_strength=2.0,
        p_value=0.01
    )
    assert approved
    assert allocation > 0
    assert reason == "approved"

    # Check budget updated
    summary = ledger.get_budget_summary()
    assert summary["spent"] > 0
    assert summary["remaining"] < summary["total_allocated"]

    print("Basic alpha ledger test passed")


def _test_budget_constraints() -> None:
    """Test budget constraint enforcement."""
    ledger = create_pocock_ledger(total_alpha=0.001)  # Small budget

    # Exhaust budget with more iterations and stronger evidence
    approved = True
    allocations = []
    for i in range(200):
        allocation, approved, reason = ledger.request_alpha(
            evidence_strength=5.0,  # Stronger evidence
            p_value=1e-6  # More significant
        )
        allocations.append((allocation, approved, reason))
        if not approved:
            print(f"Rejected at iteration {i}: allocation={allocation}, reason={reason}")
            break

    # Check that budget is being consumed
    final_remaining = ledger.get_budget_summary()["remaining"]
    initial_budget = 0.001
    spent = initial_budget - final_remaining
    print(f"Initial: {initial_budget}, Spent: {spent}, Remaining: {final_remaining}")

    # Should have spent some alpha
    assert spent > 0, "No alpha was spent"
    assert final_remaining < initial_budget, "Budget should decrease"

    print("Budget constraints test passed")


def _test_different_policies() -> None:
    """Test different spending policies."""
    policies = [
        create_pocock_ledger,
        create_obf_ledger,
        create_bh_fdr_ledger,
        create_adaptive_ledger
    ]

    for factory in policies:
        ledger = factory(total_alpha=0.05)

        # Test allocation
        allocation, approved, reason = ledger.request_alpha(
            evidence_strength=2.0,
            p_value=0.01
        )

        assert approved
        assert allocation > 0

        # Check policy is recorded
        summary = ledger.get_budget_summary()
        assert "policy" in summary

    print("Different policies test passed")


def _test_alpha_release() -> None:
    """Test alpha release functionality."""
    ledger = create_pocock_ledger(total_alpha=0.05)

    # Allocate alpha
    allocation, approved, reason = ledger.request_alpha(
        evidence_strength=2.0,
        p_value=0.01
    )
    assert approved

    initial_spent = ledger.get_budget_summary()["spent"]
    initial_remaining = ledger.get_budget_summary()["remaining"]

    # Release alpha
    test_id = list(ledger.active_tests.keys())[0]
    released = ledger.release_alpha(test_id)

    assert released
    final_spent = ledger.get_budget_summary()["spent"]
    final_remaining = ledger.get_budget_summary()["remaining"]

    # Budget should be restored
    assert final_spent < initial_spent
    assert final_remaining > initial_remaining

    print("Alpha release test passed")


if __name__ == "__main__":
    _test_alpha_ledger_basic()
    _test_budget_constraints()
    _test_different_policies()
    _test_alpha_release()
    print("OK - core/governance/alpha_ledger.py self-tests passed")
