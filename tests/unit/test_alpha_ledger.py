"""Unit tests for Alpha Ledger transaction-based α-cost accounting."""

import json
import pytest
import threading
import time
from unittest.mock import patch

from core.governance.alpha_ledger import AlphaTxn, AlphaLedger


class TestAlphaTxn:
    """Test AlphaTxn dataclass validation."""

    def test_valid_transaction(self):
        """Test creating valid transaction."""
        txn = AlphaTxn(
            ts_ns_mono=1000000000,
            ts_ns_wall=1000000001,
            test_id="sprt:maker_edge",
            alpha0=0.05,
            spent=0.01,
            outcome="open"
        )
        assert txn.ts_ns_mono == 1000000000
        assert txn.ts_ns_wall == 1000000001
        assert txn.test_id == "sprt:maker_edge"
        assert txn.alpha0 == 0.05
        assert txn.spent == 0.01
        assert txn.outcome == "open"

    def test_negative_spent_raises(self):
        """Test that negative spent raises ValueError."""
        with pytest.raises(ValueError, match="spent cannot be negative"):
            AlphaTxn(
                ts_ns_mono=1000000000,
                ts_ns_wall=1000000001,
                test_id="test",
                alpha0=0.05,
                spent=-0.01,
                outcome="open"
            )

    def test_spent_exceeds_alpha0_raises(self):
        """Test that spent > alpha0 raises ValueError."""
        with pytest.raises(ValueError, match="spent .* exceeds alpha0"):
            AlphaTxn(
                ts_ns_mono=1000000000,
                ts_ns_wall=1000000001,
                test_id="test",
                alpha0=0.05,
                spent=0.06,
                outcome="open"
            )

    def test_invalid_outcome_raises(self):
        """Test that invalid outcome raises ValueError."""
        with pytest.raises(ValueError, match="invalid outcome"):
            AlphaTxn(
                ts_ns_mono=1000000000,
                ts_ns_wall=1000000001,
                test_id="test",
                alpha0=0.05,
                spent=0.01,
                outcome="invalid"
            )

    def test_valid_outcomes(self):
        """Test all valid outcomes are accepted."""
        valid_outcomes = ["open", "accept", "reject", "abandon"]
        for outcome in valid_outcomes:
            txn = AlphaTxn(
                ts_ns_mono=1000000000,
                ts_ns_wall=1000000001,
                test_id="test",
                alpha0=0.05,
                spent=0.01,
                outcome=outcome
            )
            assert txn.outcome == outcome


class TestAlphaLedger:
    """Test AlphaLedger α-cost accounting functionality."""

    def setup_method(self):
        """Create fresh ledger for each test."""
        self.ledger = AlphaLedger()

    def test_open_allocation(self):
        """Test opening new α-allocation."""
        token = self.ledger.open("sprt:maker_edge", alpha0=0.05)
        assert isinstance(token, str)
        assert len(token) > 0
        
        # Check transaction was created
        txn = self.ledger.get_transaction(token)
        assert txn is not None
        assert txn.test_id == "sprt:maker_edge"
        assert txn.alpha0 == 0.05
        assert txn.spent == 0.0
        assert txn.outcome == "open"

    def test_open_invalid_alpha0(self):
        """Test that invalid alpha0 values raise ValueError."""
        with pytest.raises(ValueError, match="alpha0 must be in"):
            self.ledger.open("test", alpha0=0.0)
        
        with pytest.raises(ValueError, match="alpha0 must be in"):
            self.ledger.open("test", alpha0=-0.1)
        
        with pytest.raises(ValueError, match="alpha0 must be in"):
            self.ledger.open("test", alpha0=1.5)

    def test_open_duplicate_test_id(self):
        """Test that opening same test_id twice raises ValueError."""
        self.ledger.open("test", alpha0=0.05)
        
        with pytest.raises(ValueError, match="already has active allocation"):
            self.ledger.open("test", alpha0=0.03)

    def test_spend_valid(self):
        """Test valid α spending."""
        token = self.ledger.open("test", alpha0=0.05)
        
        # Spend some α
        self.ledger.spend(token, 0.01)
        txn = self.ledger.get_transaction(token)
        assert txn.spent == 0.01
        
        # Spend more (monotonic increase)
        self.ledger.spend(token, 0.02)
        txn = self.ledger.get_transaction(token)
        assert txn.spent == 0.03

    def test_spend_invalid_token(self):
        """Test spending with invalid token raises ValueError."""
        with pytest.raises(ValueError, match="invalid token"):
            self.ledger.spend("invalid-token", 0.01)

    def test_spend_negative_amount(self):
        """Test spending negative amount raises ValueError."""
        token = self.ledger.open("test", alpha0=0.05)
        
        with pytest.raises(ValueError, match="amount must be a finite positive number"):
            self.ledger.spend(token, -0.01)

    def test_spend_exceeds_budget(self):
        """Test spending over budget raises ValueError."""
        token = self.ledger.open("test", alpha0=0.05)
        
        with pytest.raises(ValueError, match="would exceed budget"):
            self.ledger.spend(token, 0.06)

    def test_spend_on_closed_allocation(self):
        """Test spending on closed allocation raises ValueError."""
        token = self.ledger.open("test", alpha0=0.05)
        self.ledger.close(token, "accept")
        
        with pytest.raises(ValueError, match="cannot spend on closed allocation"):
            self.ledger.spend(token, 0.01)

    def test_close_allocation(self):
        """Test closing allocation with valid outcome."""
        token = self.ledger.open("test", alpha0=0.05)
        self.ledger.spend(token, 0.02)
        
        self.ledger.close(token, "accept")
        
        txn = self.ledger.get_transaction(token)
        assert txn.outcome == "accept"
        assert txn.spent == 0.02

    def test_close_invalid_token(self):
        """Test closing with invalid token raises ValueError."""
        with pytest.raises(ValueError, match="invalid token"):
            self.ledger.close("invalid-token", "accept")

    def test_close_invalid_outcome(self):
        """Test closing with invalid outcome raises ValueError."""
        token = self.ledger.open("test", alpha0=0.05)
        
        with pytest.raises(ValueError, match="outcome must be one of"):
            self.ledger.close(token, "invalid")

    def test_close_already_closed(self):
        """Test closing already closed allocation raises ValueError."""
        token = self.ledger.open("test", alpha0=0.05)
        self.ledger.close(token, "accept")
        
        with pytest.raises(ValueError, match="allocation already closed"):
            self.ledger.close(token, "reject")

    def test_summary_empty_ledger(self):
        """Test summary for empty ledger."""
        summary = self.ledger.summary()
        expected = {
            "total_alloc": 0.0,
            "total_spent": 0.0,
            "active_tests": 0,
            "closed_tests": 0,
            "by_test_id": {},
            "by_outcome": {}
        }
        assert summary == expected

    def test_summary_with_transactions(self):
        """Test summary with multiple transactions."""
        # Open and close one allocation
        token1 = self.ledger.open("test1", alpha0=0.05)
        self.ledger.spend(token1, 0.02)
        self.ledger.close(token1, "accept")
        
        # Keep one allocation open
        token2 = self.ledger.open("test2", alpha0=0.03)
        self.ledger.spend(token2, 0.01)
        
        summary = self.ledger.summary()
        
        assert summary["total_alloc"] == 0.08
        assert summary["total_spent"] == 0.03
        assert summary["active_tests"] == 1
        assert summary["closed_tests"] == 1
        
        # Check by_test_id
        assert "test1" in summary["by_test_id"]
        assert summary["by_test_id"]["test1"]["outcome"] == "accept"
        assert summary["by_test_id"]["test1"]["spent"] == 0.02
        assert summary["by_test_id"]["test1"]["utilization"] == pytest.approx(0.4)  # 0.02/0.05
        
        assert "test2" in summary["by_test_id"]
        assert summary["by_test_id"]["test2"]["outcome"] == "open"
        assert summary["by_test_id"]["test2"]["spent"] == 0.01
        
        # Check by_outcome
        assert "accept" in summary["by_outcome"]
        assert summary["by_outcome"]["accept"]["count"] == 1
        assert summary["by_outcome"]["accept"]["total_spent"] == 0.02
        
        assert "open" in summary["by_outcome"]
        assert summary["by_outcome"]["open"]["count"] == 1
        assert summary["by_outcome"]["open"]["total_spent"] == 0.01

    def test_list_transactions(self):
        """Test listing transactions."""
        token1 = self.ledger.open("test1", alpha0=0.05)
        token2 = self.ledger.open("test2", alpha0=0.03)
        
        # All transactions
        all_txns = self.ledger.list_transactions()
        assert len(all_txns) == 2
        assert all_txns[0].test_id in ["test1", "test2"]
        assert all_txns[1].test_id in ["test1", "test2"]
        
        # Filtered by test_id
        test1_txns = self.ledger.list_transactions(test_id="test1")
        assert len(test1_txns) == 1
        assert test1_txns[0].test_id == "test1"

    def test_json_serialization(self):
        """Test JSON serialization and deserialization."""
        # Create some state
        token1 = self.ledger.open("test1", alpha0=0.05)
        self.ledger.spend(token1, 0.02)
        self.ledger.close(token1, "accept")
        
        token2 = self.ledger.open("test2", alpha0=0.03)
        self.ledger.spend(token2, 0.01)
        
        # Serialize
        json_str = self.ledger.to_json()
        assert isinstance(json_str, str)
        
        # Create new ledger and deserialize
        new_ledger = AlphaLedger()
        new_ledger.from_json(json_str)
        
        # Check state was restored
        summary_orig = self.ledger.summary()
        summary_new = new_ledger.summary()
        assert summary_orig == summary_new
        
        # Check specific transaction
        txn_orig = self.ledger.get_transaction(token1)
        txn_new = new_ledger.get_transaction(token1)
        assert txn_orig.test_id == txn_new.test_id
        assert txn_orig.alpha0 == txn_new.alpha0
        assert txn_orig.spent == txn_new.spent
        assert txn_orig.outcome == txn_new.outcome

    def test_clear(self):
        """Test clearing ledger state."""
        self.ledger.open("test", alpha0=0.05)
        assert len(self.ledger.list_transactions()) == 1
        
        self.ledger.clear()
        assert len(self.ledger.list_transactions()) == 0
        
        summary = self.ledger.summary()
        assert summary["total_alloc"] == 0.0
        assert summary["active_tests"] == 0

    def test_get_transaction_returns_copy(self):
        """Test that get_transaction returns immutable copy."""
        token = self.ledger.open("test", alpha0=0.05)
        
        # Get transaction and try to mutate it
        txn = self.ledger.get_transaction(token)
        original_spent = txn.spent
        txn.spent = 999.0  # This should not affect the ledger
        
        # Check ledger state unchanged
        txn_fresh = self.ledger.get_transaction(token)
        assert txn_fresh.spent == original_spent

    def test_thread_safety(self):
        """Test thread-safe operations with concurrent access."""
        def worker(worker_id: int, results: list):
            try:
                token = self.ledger.open(f"test{worker_id}", alpha0=0.05)
                for i in range(10):
                    self.ledger.spend(token, 0.001)
                    time.sleep(0.001)  # Small delay to encourage race conditions
                self.ledger.close(token, "accept")
                results.append(True)
            except Exception as e:
                results.append(f"Worker {worker_id} failed: {e}")
        
        # Run multiple workers concurrently
        results = []
        threads = []
        for i in range(5):
            thread = threading.Thread(target=worker, args=(i, results))
            threads.append(thread)
            thread.start()
        
        # Wait for completion
        for thread in threads:
            thread.join()
        
        # Check all workers succeeded
        assert all(result is True for result in results), f"Some workers failed: {results}"
        
        # Check final state
        summary = self.ledger.summary()
        assert summary["closed_tests"] == 5
        assert summary["active_tests"] == 0
        assert summary["total_spent"] == pytest.approx(0.05)  # 5 workers × 10 spends × 0.001

    def test_reopen_after_close(self):
        """Test reopening allocation for same test_id after close."""
        # Open, close, then reopen same test_id
        token1 = self.ledger.open("test", alpha0=0.05)
        self.ledger.close(token1, "accept")
        
        # Should be able to open again with same test_id
        token2 = self.ledger.open("test", alpha0=0.03)
        assert token1 != token2
        
        # Check both transactions exist
        txn1 = self.ledger.get_transaction(token1)
        txn2 = self.ledger.get_transaction(token2)
        assert txn1.outcome == "accept"
        assert txn2.outcome == "open"

    def test_spending_edge_cases(self):
        """Test edge cases in α spending."""
        token = self.ledger.open("test", alpha0=0.05)
        
        # Spend exactly the budget
        self.ledger.spend(token, 0.05)
        txn = self.ledger.get_transaction(token)
        assert txn.spent == 0.05
        
        # Cannot spend any more
        with pytest.raises(ValueError, match="would exceed budget"):
            self.ledger.spend(token, 0.001)

    # @patch('time.time_ns')
    # def test_timestamp_monotonic(self, mock_time_ns):
    #     """Test that timestamps are monotonic."""
    #     mock_time_ns.side_effect = [1000, 2000, 3000]
    #     
    #     token1 = self.ledger.open("test1", alpha0=0.05)
    #     token2 = self.ledger.open("test2", alpha0=0.03)
    #     token3 = self.ledger.open("test3", alpha0=0.02)
    #     
    #     txns = self.ledger.list_transactions()
    #     assert len(txns) == 3
    #     assert txns[0].ts_ns == 1000
    #     assert txns[1].ts_ns == 2000  
    #     assert txns[2].ts_ns == 3000