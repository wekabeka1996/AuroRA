"""
Unit tests for idem_guard basic functionality.

Simple unit tests targeting coverage gaps in core/execution/idem_guard.py.
"""

import json
from unittest.mock import Mock, patch

import pytest

from core.execution.idem_guard import (
    IdempotencyConflict,
    mark_status,
    pre_submit_check,
    set_event_logger,
    set_idem_metrics,
)


class TestIdemGuardBasics:
    """Basic idem_guard functionality tests."""

    def setup_method(self):
        """Setup test environment."""
        self.mock_logger = Mock()
        set_event_logger(self.mock_logger)
        set_idem_metrics(None)

    def test_pre_submit_check_not_found(self):
        """Test pre_submit_check returns None for non-existent key."""
        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = None

            result = pre_submit_check("new_coid", "spec_hash_123", 3600.0)
            assert result is None, "Should return None for non-existent key"
            mock_store.get.assert_called_once_with("new_coid")

    def test_pre_submit_check_hit_scenario(self):
        """Test pre_submit_check returns cached data on HIT."""
        cached_data = {
            "spec_hash": "spec_hash_123",
            "status": "FILLED",
            "updated": 1694419200,
        }

        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = json.dumps(cached_data)

            result = pre_submit_check("existing_coid", "spec_hash_123", 3600.0)
            # Result should be a dict, not JSON string
            assert result == cached_data, "Should return cached data on HIT"

    def test_pre_submit_check_conflict_detection(self):
        """Test pre_submit_check raises IdempotencyConflict on spec mismatch."""
        cached_data = {
            "spec_hash": "different_spec_hash",
            "status": "PENDING",
            "updated": 1694419200,
        }

        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = json.dumps(cached_data)

            with pytest.raises(IdempotencyConflict):
                pre_submit_check("conflict_coid", "new_spec_hash", 3600.0)

    def test_mark_status_basic(self):
        """Test mark_status basic functionality."""
        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = None  # No existing data

            mark_status("test_coid", "ACK", 3600.0)

            # Should call put with JSON data
            mock_store.put.assert_called_once()
            call_args = mock_store.put.call_args
            assert call_args[0][0] == "test_coid", "Should use correct client_order_id"

            # Parse the JSON data
            json_data = json.loads(call_args[0][1])
            assert json_data["status"] == "ACK", "Should set correct status"

    def test_mark_status_preserves_spec_hash(self):
        """Test mark_status preserves existing spec_hash."""
        existing_data = {
            "spec_hash": "existing_spec_123",
            "status": "PENDING",
            "updated": 1694419100,
        }

        with patch("core.execution.idem_guard._STORE") as mock_store:
            mock_store.get.return_value = json.dumps(existing_data)

            mark_status("preserve_coid", "FILLED", 3600.0)

            # Should preserve spec_hash
            call_args = mock_store.put.call_args
            json_data = json.loads(call_args[0][1])
            assert (
                json_data["spec_hash"] == "existing_spec_123"
            ), "Should preserve spec_hash"
            assert json_data["status"] == "FILLED", "Should update status"

    def test_set_event_logger(self):
        """Test set_event_logger functionality."""
        new_logger = Mock()
        set_event_logger(new_logger)

        # Should accept logger without error
        set_event_logger(None)  # Should also work with None

    def test_set_idem_metrics(self):
        """Test set_idem_metrics functionality."""
        mock_metrics = Mock()
        set_idem_metrics(mock_metrics)

        # Should accept metrics without error
        set_idem_metrics(None)  # Should also work with None
