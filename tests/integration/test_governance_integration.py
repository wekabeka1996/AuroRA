"""Integration tests for P3-α governance system."""


import numpy as np
import pytest

from core.governance.alpha_ledger import AlphaLedger
from core.governance.sprt_glr import CompositeSPRT, SPRTConfig, SPRTOutcome


class TestGovernanceIntegration:
    """Test integration between alpha ledger and SPRT/GLR modules."""

    def setup_method(self):
        """Set up test components."""
        self.ledger = AlphaLedger()
        self.sprt_config = SPRTConfig(mu0=0.0, mu1=1.0, alpha=0.05, beta=0.2, min_samples=5)

    def test_alpha_spending_workflow(self):
        """Test complete alpha spending workflow with SPRT."""
        # Open alpha allocation for trading edge test
        token = self.ledger.open("edge_test_btcusdt", alpha0=0.05)

        # Create SPRT instance
        sprt = CompositeSPRT(self.sprt_config)

        # Simulate sequential testing with alpha spending
        np.random.seed(42)
        test_data = np.random.normal(0.5, 1.0, 20)  # Data favoring H1

        total_spent = 0.0
        decision = None

        for i, observation in enumerate(test_data):
            # Update SPRT
            decision = sprt.update(observation)

            # Spend small amount of alpha for each test
            spend_amount = 0.001  # 0.1% of alpha budget
            if total_spent + spend_amount <= 0.05:
                self.ledger.spend(token, spend_amount)
                total_spent += spend_amount

            # Stop if SPRT makes decision
            if decision.stop:
                break

        # Close allocation with final outcome
        outcome = "accept" if decision.outcome == SPRTOutcome.ACCEPT_H1 else "reject"
        self.ledger.close(token, outcome)

        # Verify integration
        assert decision is not None
        assert decision.stop is True

        # Check alpha ledger state
        txn = self.ledger.get_transaction(token)
        assert txn.outcome == outcome
        assert txn.spent <= 0.05  # Within budget
        assert txn.spent > 0.0    # Some alpha was spent

    def test_multiple_concurrent_tests(self):
        """Test multiple concurrent statistical tests with shared alpha budget."""
        # Open allocations for different symbols
        tokens = {}
        for symbol in ["BTCUSDT", "ETHUSDT", "SOLUSDT"]:
            tokens[symbol] = self.ledger.open(f"edge_test_{symbol.lower()}", alpha0=0.02)

        # Create SPRT instances for each symbol
        sprts = {}
        for symbol in tokens:
            sprts[symbol] = CompositeSPRT(self.sprt_config)

        # Simulate concurrent testing
        np.random.seed(123)
        results = {}

        for symbol in tokens:
            # Different data patterns for each symbol
            if symbol == "BTCUSDT":
                data = np.random.normal(0.8, 1.0, 15)  # Strong H1
            elif symbol == "ETHUSDT":
                data = np.random.normal(-0.3, 1.0, 15)  # Weak H0
            else:
                data = np.random.normal(0.2, 1.0, 15)  # Ambiguous

            token = tokens[symbol]
            sprt = sprts[symbol]

            for observation in data:
                decision = sprt.update(observation)

                # Spend alpha proportional to confidence
                spend_amount = 0.0005 * decision.confidence if decision.confidence > 0 else 0.0001
                try:
                    self.ledger.spend(token, spend_amount)
                except ValueError:
                    # Budget exhausted
                    pass

                if decision.stop:
                    break

            # Close allocation
            outcome = "accept" if decision.outcome == SPRTOutcome.ACCEPT_H1 else "reject"
            self.ledger.close(token, outcome)
            results[symbol] = decision

        # Verify all tests completed
        assert len(results) == 3
        for symbol, decision in results.items():
            assert decision is not None

            # Check ledger state
            txn = self.ledger.get_transaction(tokens[symbol])
            assert txn.outcome in ["accept", "reject"]
            assert txn.spent <= 0.02  # Within individual budget

    def test_alpha_budget_exhaustion(self):
        """Test behavior when alpha budget is exhausted."""
        # Small alpha budget
        token = self.ledger.open("limited_test", alpha0=0.001)
        sprt = CompositeSPRT(self.sprt_config)

        # Try to spend more than budget allows
        spent_count = 0
        for i in range(10):
            try:
                self.ledger.spend(token, 0.0005)  # 0.05% each
                spent_count += 1
            except ValueError:
                # Budget exhausted
                break

        # Should be able to spend at most 2 times (2 * 0.0005 = 0.001)
        assert spent_count == 2

        # Transaction should still be open
        txn = self.ledger.get_transaction(token)
        assert txn.outcome == "open"
        assert txn.spent == 0.001  # Exactly the budget

        # Close with abandon since budget exhausted
        self.ledger.close(token, "abandon")

        # Verify final state
        txn = self.ledger.get_transaction(token)
        assert txn.outcome == "abandon"

    def test_governance_metrics_computation(self):
        """Test computation of governance metrics for decision logging."""
        token = self.ledger.open("metrics_test", alpha0=0.05)
        sprt = CompositeSPRT(self.sprt_config)

        # Add data to SPRT
        observations = [0.5, 0.7, 0.9, 1.1, 1.3]
        spent_amounts = []

        for obs in observations:
            decision = sprt.update(obs)

            # Spend alpha based on LLR magnitude
            spend_amount = min(0.005, abs(decision.llr) * 0.001)
            if spend_amount > 0:
                self.ledger.spend(token, spend_amount)
                spent_amounts.append(spend_amount)

            if decision.stop:
                break

        # Compute governance metrics
        txn = self.ledger.get_transaction(token)
        summary = sprt.get_summary()

        # Metrics that would be logged to XAI/DecisionTrace
        governance_metrics = {
            "sprt_llr": summary["llr"],
            "sprt_conf": summary["confidence"],
            "alpha_spent": txn.spent,
            "alpha_utilization": txn.spent / txn.alpha0,
            "n_samples": summary["n_samples"],
            "test_outcome": decision.outcome.value if decision.stop else "continue"
        }

        # Verify metrics are reasonable
        assert isinstance(governance_metrics["sprt_llr"], float)
        assert 0.0 <= governance_metrics["sprt_conf"] <= 1.0
        assert 0.0 <= governance_metrics["alpha_spent"] <= 0.05
        assert 0.0 <= governance_metrics["alpha_utilization"] <= 1.0
        assert governance_metrics["n_samples"] == len(observations)

        # Close allocation
        outcome = "accept" if decision.outcome == SPRTOutcome.ACCEPT_H1 else "abandon"
        if decision.stop:
            self.ledger.close(token, outcome)

    def test_error_handling_integration(self):
        """Test error handling in integrated governance system."""
        token = self.ledger.open("error_test", alpha0=0.01)
        sprt = CompositeSPRT(self.sprt_config)

        # Test invalid spending after close
        self.ledger.spend(token, 0.005)
        self.ledger.close(token, "accept")

        with pytest.raises(ValueError, match="cannot spend on closed allocation"):
            self.ledger.spend(token, 0.001)

        # Test SPRT with edge cases
        decision = sprt.update(float('inf'))  # Should handle gracefully
        assert not decision.stop  # Should continue with inf input

        decision = sprt.update(0.0)  # Normal input
        assert decision is not None

    def test_serialization_integration(self):
        """Test JSON serialization of integrated governance state."""
        # Create some state
        token1 = self.ledger.open("ser_test1", alpha0=0.02)
        token2 = self.ledger.open("ser_test2", alpha0=0.03)

        self.ledger.spend(token1, 0.01)
        self.ledger.close(token1, "accept")

        self.ledger.spend(token2, 0.005)
        # Leave token2 open

        # Serialize ledger state
        json_state = self.ledger.to_json()
        assert isinstance(json_state, str)

        # Create new ledger and deserialize
        new_ledger = AlphaLedger()
        new_ledger.from_json(json_state)

        # Verify state was restored
        txn1 = new_ledger.get_transaction(token1)
        txn2 = new_ledger.get_transaction(token2)

        assert txn1.outcome == "accept"
        assert txn1.spent == 0.01

        assert txn2.outcome == "open"
        assert txn2.spent == 0.005

        # Should be able to continue operations
        new_ledger.spend(token2, 0.01)
        new_ledger.close(token2, "reject")

    def test_performance_integration(self):
        """Test performance of integrated governance system."""
        import time

        # Large number of concurrent tests
        n_tests = 100
        tokens = []
        sprts = []

        # Setup phase
        start_time = time.time()
        for i in range(n_tests):
            token = self.ledger.open(f"perf_test_{i}", alpha0=0.001)
            tokens.append(token)
            sprts.append(CompositeSPRT(self.sprt_config))
        setup_time = time.time() - start_time

        # Execution phase
        start_time = time.time()
        np.random.seed(456)
        for i in range(n_tests):
            sprt = sprts[i]
            token = tokens[i]

            # Quick test with few samples
            for _ in range(3):
                observation = np.random.normal(0.0, 1.0)
                decision = sprt.update(observation)
                self.ledger.spend(token, 0.0001)

                if decision.stop:
                    break

            # Close
            outcome = "accept" if decision.outcome == SPRTOutcome.ACCEPT_H1 else "abandon"
            self.ledger.close(token, outcome)

        execution_time = time.time() - start_time

        # Performance assertions (reasonable thresholds)
        assert setup_time < 1.0  # Setup should be fast
        assert execution_time < 2.0  # Execution should be reasonably fast
        assert len(self.ledger.list_transactions()) == n_tests

        # Verify summary performance
        start_time = time.time()
        summary = self.ledger.summary()
        summary_time = time.time() - start_time

        assert summary_time < 0.1  # Summary should be very fast
        assert summary["closed_tests"] == n_tests
        assert summary["active_tests"] == 0
