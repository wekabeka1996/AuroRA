"""Tests for patched AlphaLedger with monotonic time, audit history, and ε-tolerance."""

import json
import pytest
import threading
import time
from unittest.mock import Mock

from core.governance.alpha_ledger import AlphaLedger, AlphaTxn


class TestAlphaLedgerPatched:
    """Test suite for enhanced AlphaLedger functionality."""

    def test_open_spend_close_invariants(self):
        """Test open→spend(0.001)→spend(0.002)→close("accept") invariants."""
        mock_clock = Mock()
        mock_clock.side_effect = [1000, 2000, 3000, 4000]  # monotonic timestamps
        
        ledger = AlphaLedger(clock_ns=mock_clock)
        
        # Open allocation
        token = ledger.open("test_momentum", alpha0=0.01)
        assert ledger.is_open(token)
        
        # First spend
        ledger.spend(token, 0.001)
        txn = ledger.get_transaction(token)
        assert txn.spent == 0.001
        assert len(txn.history) == 1
        assert txn.history[0]["amount"] == 0.001
        assert txn.history[0]["spent"] == 0.001
        assert txn.history[0]["ts_ns"] == 2000
        
        # Second spend (monotonic)
        ledger.spend(token, 0.002)
        txn = ledger.get_transaction(token)
        assert txn.spent == 0.003
        assert len(txn.history) == 2
        assert txn.history[1]["amount"] == 0.002
        assert txn.history[1]["spent"] == 0.003
        
        # Close
        ledger.close(token, "accept")
        txn = ledger.get_transaction(token)
        assert not ledger.is_open(token)
        assert txn.outcome == "accept"
        assert txn.closed_ts_ns == 4000
        assert ledger.remaining(token) == 0.007

    def test_spend_overshoot_eps(self):
        """Test ε-tolerance for budget boundary spending."""
        ledger = AlphaLedger(eps=1e-12)
        token = ledger.open("test_boundary", alpha0=0.01)
        
        # Spend up to boundary
        ledger.spend(token, 0.005)
        ledger.spend(token, 0.003)
        ledger.spend(token, 0.001)  # total: 0.009
        
        # Spend that would overshoot by small epsilon (should be clamped)
        overshoot_amount = 0.001 + 5e-13  # within eps tolerance
        ledger.spend(token, overshoot_amount)
        
        txn = ledger.get_transaction(token)
        assert txn.spent == 0.01  # clamped to alpha0
        assert ledger.remaining(token) == 0.0

    def test_spend_exceeds_budget_raises(self):
        """Test that spending beyond alpha0+eps raises ValueError."""
        ledger = AlphaLedger(eps=1e-12)
        token = ledger.open("test_exceed", alpha0=0.01)
        
        # Spend most of budget
        ledger.spend(token, 0.008)
        
        # Attempt to exceed budget beyond ε-tolerance
        with pytest.raises(ValueError, match="would exceed budget"):
            ledger.spend(token, 0.003)  # 0.008 + 0.003 = 0.011 > 0.01 + eps

    def test_active_allocation_guard(self):
        """Test that duplicate open() for same test_id raises, but after close is allowed."""
        ledger = AlphaLedger()
        
        # First allocation
        token1 = ledger.open("test_guard", alpha0=0.01)
        
        # Duplicate allocation should fail
        with pytest.raises(ValueError, match="already has active allocation"):
            ledger.open("test_guard", alpha0=0.02)
        
        # Close first allocation
        ledger.close(token1, "accept")
        
        # New allocation should succeed
        token2 = ledger.open("test_guard", alpha0=0.02)
        assert token2 != token1
        assert ledger.is_open(token2)

    def test_to_from_json_roundtrip(self):
        """Test JSON serialization preserves history and all fields."""
        ledger1 = AlphaLedger()
        
        # Create transaction with multiple spends
        token = ledger1.open("test_json", alpha0=0.01)
        ledger1.spend(token, 0.003)
        ledger1.spend(token, 0.002)
        ledger1.close(token, "accept")
        
        # Serialize
        json_str = ledger1.to_json()
        
        # Deserialize into new ledger
        ledger2 = AlphaLedger()
        ledger2.from_json(json_str)
        
        # Compare transaction
        txn1 = ledger1.get_transaction(token)
        txn2 = ledger2.get_transaction(token)
        
        assert txn1.ts_ns == txn2.ts_ns
        assert txn1.test_id == txn2.test_id
        assert txn1.alpha0 == txn2.alpha0
        assert txn1.spent == txn2.spent
        assert txn1.outcome == txn2.outcome
        assert txn1.closed_ts_ns == txn2.closed_ts_ns
        assert len(txn1.history) == len(txn2.history) == 2
        assert txn1.history == txn2.history

    def test_concurrent_spend_threads(self):
        """Test thread safety with concurrent spending."""
        ledger = AlphaLedger()
        token = ledger.open("test_concurrent", alpha0=0.4)  # 4 threads × 100 spends × 0.001
        
        def spend_worker():
            for _ in range(100):
                try:
                    ledger.spend(token, 0.001)
                except ValueError:
                    # Expected when budget exhausted
                    pass
        
        # Start 4 concurrent threads
        threads = [threading.Thread(target=spend_worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        
        txn = ledger.get_transaction(token)
        # Should have spent exactly alpha0 (no overspend)
        assert txn.spent == 0.4
        assert len(txn.history) == 400  # All 400 spends recorded

    def test_list_and_get_transaction_are_copies(self):
        """Test that returned transactions are copies, not references."""
        ledger = AlphaLedger()
        token = ledger.open("test_copy", alpha0=0.01)
        ledger.spend(token, 0.005)
        
        # Get transaction and modify it
        txn1 = ledger.get_transaction(token)
        txn1.spent = 999.0  # modify copy
        txn1.history.append({"fake": "entry"})  # modify history copy
        
        # Original should be unchanged
        txn2 = ledger.get_transaction(token)
        assert txn2.spent == 0.005
        assert len(txn2.history) == 1
        assert "fake" not in str(txn2.history)
        
        # Same for list_transactions
        txns = ledger.list_transactions()
        txns[0].spent = 888.0
        txns[0].history.clear()
        
        txn3 = ledger.get_transaction(token)
        assert txn3.spent == 0.005
        assert len(txn3.history) == 1

    def test_summary_fields(self):
        """Test summary includes remaining, utilization, and proper aggregations."""
        ledger = AlphaLedger()
        
        # Create multiple transactions
        token1 = ledger.open("test_summary1", alpha0=0.01)
        ledger.spend(token1, 0.007)
        ledger.close(token1, "accept")
        
        token2 = ledger.open("test_summary2", alpha0=0.02)
        ledger.spend(token2, 0.005)
        ledger.close(token2, "reject")
        
        summary = ledger.summary()
        
        # Check global stats
        assert summary["total_alloc"] == 0.03
        assert summary["total_spent"] == 0.012
        assert summary["active_tests"] == 0
        assert summary["closed_tests"] == 2
        
        # Check per-test breakdown
        test1_info = summary["by_test_id"]["test_summary1"]
        assert test1_info["alpha0"] == 0.01
        assert test1_info["spent"] == 0.007
        assert test1_info["outcome"] == "accept"
        assert test1_info["utilization"] == 0.7
        assert test1_info["remaining"] == 0.003
        
        # Check by-outcome aggregation
        assert summary["by_outcome"]["accept"]["count"] == 1
        assert summary["by_outcome"]["accept"]["total_spent"] == 0.007
        assert summary["by_outcome"]["reject"]["count"] == 1
        assert summary["by_outcome"]["reject"]["total_spent"] == 0.005

    def test_continue_outcome_removed(self):
        """Test that 'continue' is no longer a valid outcome."""
        ledger = AlphaLedger()
        token = ledger.open("test_no_continue", alpha0=0.01)
        
        with pytest.raises(ValueError, match="outcome must be one of"):
            ledger.close(token, "continue")

    def test_convenience_helpers(self):
        """Test is_open, remaining, active_token_for helper methods."""
        ledger = AlphaLedger()
        
        # Test active_token_for before allocation
        assert ledger.active_token_for("test_helpers") is None
        
        # Open allocation
        token = ledger.open("test_helpers", alpha0=0.01)
        
        # Test helpers on open allocation
        assert ledger.is_open(token)
        assert ledger.remaining(token) == 0.01
        assert ledger.active_token_for("test_helpers") == token
        
        # Spend some
        ledger.spend(token, 0.003)
        assert ledger.remaining(token) == 0.007
        
        # Close
        ledger.close(token, "accept")
        assert not ledger.is_open(token)
        assert ledger.remaining(token) == 0.007
        assert ledger.active_token_for("test_helpers") is None