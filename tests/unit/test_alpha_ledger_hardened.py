"""Additional tests for hardened AlphaLedger with migration, bounded history, and NaN/inf validation."""

import json
import math
import pytest
from unittest.mock import Mock

from core.governance.alpha_ledger import AlphaLedger, AlphaTxn


class TestAlphaLedgerHardened:
    """Tests for hardened AlphaLedger features."""

    def test_json_migration_from_legacy(self):
        """Test JSON round-trip with old format (without new fields) doesn't fail."""
        # Create legacy JSON format (old ts_ns field, continue outcome)
        legacy_json = {
            "transactions": {
                "token123": {
                    "ts_ns": 1000000000,  # old field name
                    "test_id": "legacy_test",
                    "alpha0": 0.01,
                    "spent": 0.005,
                    "outcome": "continue",  # old outcome
                    "token": "token123"
                    # no history, closed_ts_ns, ts_ns_mono, ts_ns_wall
                }
            },
            "test_index": {
                "legacy_test": "token123"
            }
        }
        
        # Load into new ledger
        ledger = AlphaLedger()
        ledger.from_json(json.dumps(legacy_json))
        
        # Check migration succeeded
        txn = ledger.get_transaction("token123")
        assert txn is not None
        assert txn.test_id == "legacy_test"
        assert txn.alpha0 == 0.01
        assert txn.spent == 0.005
        assert txn.outcome == "open"  # continue → open
        assert hasattr(txn, "ts_ns_mono")
        assert hasattr(txn, "ts_ns_wall")
        assert hasattr(txn, "history")
        assert isinstance(txn.history, list)

    def test_bounded_history_overflow(self):
        """Test history truncation after max_history_len+10 spends."""
        max_len = 50
        ledger = AlphaLedger(max_history_len=max_len)
        token = ledger.open("test_history", alpha0=1.0)  # large budget
        
        # Spend more than max_history_len times
        num_spends = max_len + 10
        expected_total = 0.01 * num_spends
        for i in range(num_spends):
            ledger.spend(token, 0.01)  # small amounts
        
        txn = ledger.get_transaction(token)
        # History should be truncated to max_len
        assert len(txn.history) == max_len
        
        # Total spent should equal all spends regardless of history truncation (with floating point tolerance)
        assert txn.spent == pytest.approx(expected_total, rel=1e-9)
        
        # History should contain the most recent max_len entries
        last_entry = txn.history[-1]
        # The last entry contains cumulative spent up to that point after truncation
        assert last_entry["spent"] == pytest.approx(txn.spent, rel=1e-9)  # should match total spent

    def test_nan_inf_amount_rejection(self):
        """Test rejection of NaN and inf amounts."""
        ledger = AlphaLedger()
        token = ledger.open("test_invalid", alpha0=0.01)
        
        # Test NaN
        with pytest.raises(ValueError, match="must be a finite positive number"):
            ledger.spend(token, float('nan'))
        
        # Test positive infinity
        with pytest.raises(ValueError, match="must be a finite positive number"):
            ledger.spend(token, float('inf'))
        
        # Test negative infinity
        with pytest.raises(ValueError, match="must be a finite positive number"):
            ledger.spend(token, float('-inf'))
        
        # Test negative amount (should also fail)
        with pytest.raises(ValueError, match="must be a finite positive number"):
            ledger.spend(token, -0.001)
        
        # Test zero amount (should also fail)
        with pytest.raises(ValueError, match="must be a finite positive number"):
            ledger.spend(token, 0.0)
        
        # Verify transaction state unchanged after failures
        txn = ledger.get_transaction(token)
        assert txn.spent == 0.0
        assert len(txn.history) == 0

    def test_dual_timestamp_fields(self):
        """Test that both monotonic and wall clock timestamps are set."""
        mock_mono = Mock()
        mock_mono.side_effect = [1000, 2000, 3000]  # monotonic times
        
        # Create ledger with mocked monotonic clock
        ledger = AlphaLedger(clock_ns=mock_mono)
        
        # Open transaction
        token = ledger.open("test_dual_time", alpha0=0.01)
        
        txn = ledger.get_transaction(token)
        assert txn.ts_ns_mono == 1000  # from mock
        assert txn.ts_ns_wall > 0  # real wall clock time
        assert isinstance(txn.ts_ns_wall, int)
        
        # Spend and check history timestamp
        ledger.spend(token, 0.001)
        
        txn = ledger.get_transaction(token)
        assert len(txn.history) == 1
        assert txn.history[0]["ts_ns"] == 2000  # from mock (monotonic)
        
        # Close and check closed timestamp
        ledger.close(token, "accept")
        
        txn = ledger.get_transaction(token)
        assert txn.closed_ts_ns == 3000  # from mock (monotonic)

    def test_summary_includes_wall_time(self):
        """Test that summary includes wall time information."""
        ledger = AlphaLedger()
        token = ledger.open("test_summary_wall", alpha0=0.01)
        ledger.spend(token, 0.005)
        ledger.close(token, "accept")
        
        summary = ledger.summary()
        test_info = summary["by_test_id"]["test_summary_wall"]
        
        # Check that ts_ns_wall is included in summary
        assert "ts_ns_wall" in test_info
        assert isinstance(test_info["ts_ns_wall"], int)
        assert test_info["ts_ns_wall"] > 0