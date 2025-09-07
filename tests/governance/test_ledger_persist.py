"""
Persistence tests for AlphaLedger: snapshot/restore/throttling
===========================================================

Tests P3-B persistence features:
- Atomic snapshot/restore roundtrip
- Throttling behavior (time/event limits)
- Corrupt file handling
- File integrity validation
"""

import json
import os
import tempfile
import threading
import time
from pathlib import Path
from unittest.mock import Mock

import pytest

from core.governance.alpha_ledger import AlphaLedger


class TestLedgerPersistence:
    """Test persistence functionality of AlphaLedger."""

    def test_snapshot_restore_roundtrip(self):
        """Test complete snapshot->restore roundtrip preserves state."""
        # Create ledger with transactions
        ledger1 = AlphaLedger()
        
        # Open multiple transactions
        token1 = ledger1.open("test1", alpha0=0.05)
        token2 = ledger1.open("test2", alpha0=0.03)
        
        # Spend some alpha
        ledger1.spend(token1, 0.01)
        ledger1.spend(token1, 0.005)
        ledger1.spend(token2, 0.02)
        
        # Close one transaction
        ledger1.close(token1, "accept")
        
        # Snapshot to temp file
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            snapshot_path = Path(f.name)
        
        try:
            # Snapshot
            success = ledger1.snapshot(snapshot_path)
            assert success, "Snapshot should succeed"
            assert snapshot_path.exists(), "Snapshot file should exist"
            
            # Create new ledger and restore
            ledger2 = AlphaLedger()
            success = ledger2.restore(snapshot_path)
            assert success, "Restore should succeed"
            
            # Verify state preserved
            # Check token1 (closed)
            txn1 = ledger2.get_transaction(token1)
            assert txn1 is not None
            assert txn1.test_id == "test1"
            assert txn1.alpha0 == 0.05
            assert txn1.spent == 0.015  # 0.01 + 0.005
            assert txn1.outcome == "accept"
            assert txn1.closed_ts_ns is not None
            assert len(txn1.history) == 2  # Two spend operations
            
            # Check token2 (still open)
            txn2 = ledger2.get_transaction(token2)
            assert txn2 is not None
            assert txn2.test_id == "test2"
            assert txn2.alpha0 == 0.03
            assert txn2.spent == 0.02
            assert txn2.outcome == "open"
            assert txn2.closed_ts_ns is None
            assert len(txn2.history) == 1  # One spend operation
            
            # Check active token index
            assert ledger2.active_token_for("test1") is None  # Closed
            assert ledger2.active_token_for("test2") == token2  # Still active
            
            # Verify summary consistency
            summary1 = ledger1.summary()
            summary2 = ledger2.summary()
            assert summary1["total_spent"] == summary2["total_spent"]
            assert summary1["active_tests"] == summary2["active_tests"]
            assert summary1["closed_tests"] == summary2["closed_tests"]
        
        finally:
            # Cleanup
            snapshot_path.unlink(missing_ok=True)

    def test_snapshot_throttling(self):
        """Test that throttling prevents excessive snapshots."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            snapshot_path = Path(f.name)
        
        try:
            # Mock clock to control timing
            mock_time_ns = 1000000000000  # Start time
            
            def mock_clock():
                return mock_time_ns
            
            ledger = AlphaLedger(clock_ns=mock_clock)
            
            # Initial snapshot should succeed
            result1 = ledger.maybe_snapshot(snapshot_path, max_interval_ms=5000, max_events=50, now_ns=mock_time_ns)
            assert result1, "First snapshot should succeed"
            
            # Get file modification time
            stat1 = snapshot_path.stat()
            
            # Immediate second attempt should fail (throttled)
            result2 = ledger.maybe_snapshot(snapshot_path, max_interval_ms=5000, max_events=50, now_ns=mock_time_ns)
            assert not result2, "Second snapshot should be throttled"
            
            # File should not be modified
            stat2 = snapshot_path.stat()
            assert stat1.st_mtime == stat2.st_mtime, "File should not be modified when throttled"
            
            # Advance time beyond threshold
            mock_time_ns += 6000 * 1_000_000  # 6 seconds (> 5000ms threshold)
            
            # Should succeed after time threshold
            result3 = ledger.maybe_snapshot(snapshot_path, max_interval_ms=5000, max_events=50, now_ns=mock_time_ns)
            assert result3, "Snapshot should succeed after time threshold"
            
            # File should be modified
            stat3 = snapshot_path.stat()
            assert stat3.st_mtime > stat2.st_mtime, "File should be modified after successful snapshot"
            
        finally:
            snapshot_path.unlink(missing_ok=True)

    def test_snapshot_event_throttling(self):
        """Test throttling based on event count."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f:
            snapshot_path = Path(f.name)
        
        try:
            mock_time_ns = 1000000000000
            
            def mock_clock():
                return mock_time_ns
            
            ledger = AlphaLedger(clock_ns=mock_clock)
            token = ledger.open("test", alpha0=0.1)
            
            # Initial snapshot should succeed
            result1 = ledger.maybe_snapshot(snapshot_path, max_interval_ms=50000, max_events=3, now_ns=mock_time_ns)
            assert result1, "Initial snapshot should succeed"
            
            # Do some operations (below event threshold)
            ledger.spend(token, 0.01)  # Event 1
            ledger.spend(token, 0.01)  # Event 2
            
            # Should be throttled (only 2 events)
            result2 = ledger.maybe_snapshot(snapshot_path, max_interval_ms=50000, max_events=3, now_ns=mock_time_ns)
            assert not result2, "Should be throttled below event threshold"
            
            # One more event should trigger snapshot
            ledger.spend(token, 0.01)  # Event 3
            
            result3 = ledger.maybe_snapshot(snapshot_path, max_interval_ms=50000, max_events=3, now_ns=mock_time_ns)
            assert result3, "Should snapshot after event threshold reached"
            
        finally:
            snapshot_path.unlink(missing_ok=True)

    def test_restore_corrupt_file(self):
        """Test handling of corrupt/invalid JSON files."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
            # Write invalid JSON
            f.write('{"invalid": json content}')
            corrupt_path = Path(f.name)
        
        try:
            ledger = AlphaLedger()
            
            # Restore should fail gracefully
            success = ledger.restore(corrupt_path)
            assert not success, "Restore of corrupt file should fail"
            
            # Original file should be renamed
            assert not corrupt_path.exists(), "Original corrupt file should be moved"
            
            # Find the renamed corrupt file
            corrupt_files = list(corrupt_path.parent.glob(f"{corrupt_path.stem}.corrupt-*.json"))
            assert len(corrupt_files) == 1, "Should create exactly one corrupt backup"
            
            # Ledger should be empty after failed restore
            assert len(ledger.list_transactions()) == 0, "Ledger should be empty after failed restore"
            
            # Cleanup renamed file
            corrupt_files[0].unlink()
            
        finally:
            # Cleanup any remaining files
            corrupt_path.unlink(missing_ok=True)

    def test_restore_missing_file(self):
        """Test restore behavior with missing file."""
        missing_path = Path("/nonexistent/path/missing.json")
        
        ledger = AlphaLedger()
        success = ledger.restore(missing_path)
        
        assert not success, "Restore of missing file should return False"
        assert len(ledger.list_transactions()) == 0, "Ledger should remain empty"

    def test_atomic_snapshot_integrity(self):
        """Test that snapshot files are written atomically and don't get corrupted."""
        with tempfile.TemporaryDirectory() as temp_dir:
            snapshot_path = Path(temp_dir) / "atomic_test.json"
            
            # Create ledger with state
            ledger = AlphaLedger()
            token1 = ledger.open("test1", alpha0=0.1)
            token2 = ledger.open("test2", alpha0=0.2)
            ledger.spend(token1, 0.05)
            
            # First snapshot should succeed
            success1 = ledger.snapshot(snapshot_path)
            assert success1, "First snapshot should succeed"
            assert snapshot_path.exists(), "Snapshot file should be created"
            
            # Modify state and snapshot again
            ledger.spend(token2, 0.1)
            success2 = ledger.snapshot(snapshot_path)
            assert success2, "Second snapshot should succeed"
            
            # Verify file integrity after multiple writes
            with open(snapshot_path, 'r') as f:
                data = json.load(f)  # Should parse without error
            
            # Verify content reflects final state
            assert data['version'] == 1
            assert len(data['transactions']) == 2
            
            # Verify transactions have correct remaining alpha
            txn_data = list(data['transactions'].values())
            test1_txn = next(t for t in txn_data if t['test_id'] == 'test1')
            test2_txn = next(t for t in txn_data if t['test_id'] == 'test2')
            
            assert test1_txn['alpha0'] - test1_txn['spent'] == 0.05  # 0.1 - 0.05
            assert test2_txn['alpha0'] - test2_txn['spent'] == 0.1   # 0.2 - 0.1

    def test_version_compatibility(self):
        """Test backward compatibility with legacy snapshot format."""
        with tempfile.NamedTemporaryFile(suffix='.json', delete=False, mode='w') as f:
            # Create legacy format (no version field)
            legacy_data = {
                "transactions": {},
                "test_index": {}
            }
            json.dump(legacy_data, f)
            legacy_path = Path(f.name)
        
        try:
            ledger = AlphaLedger()
            
            # Should restore successfully
            success = ledger.restore(legacy_path)
            assert success, "Should restore legacy format"
            
            # Should be empty but functional
            assert len(ledger.list_transactions()) == 0
            
            # Should be able to add new transactions
            token = ledger.open("test", alpha0=0.1)
            assert token is not None
            
            # New snapshot should include version
            with tempfile.NamedTemporaryFile(suffix='.json', delete=False) as f2:
                new_path = Path(f2.name)
            
            try:
                success = ledger.snapshot(new_path)
                assert success, "Should be able to snapshot after legacy restore"
                
                with open(new_path, 'r') as f:
                    data = json.load(f)
                
                assert data['version'] == 1, "New snapshot should have version"
                
            finally:
                new_path.unlink(missing_ok=True)
                
        finally:
            legacy_path.unlink(missing_ok=True)