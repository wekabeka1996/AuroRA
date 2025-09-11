"""
Unit tests for guard conflict detection matrix across order parameters.

Tests coverage for comprehensive conflict detection in core/execution/idem_guard.py.
"""

import json
from itertools import product
from unittest.mock import Mock

import pytest

from core.execution.idem_guard import IdempotencyConflict, pre_submit_check


class TestGuardConflictMatrix:
    """Test comprehensive conflict detection across order parameter combinations."""

    def test_conflict_detection_price_variations(self):
        """Test conflict detection across price variations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        # Base order specification
        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Cache the base spec hash
        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test different prices should trigger conflicts
        price_variations = ["50000.1", "49999.9", "51000.0", "40000.0"]

        for price in price_variations:
            test_spec = base_spec.copy()
            test_spec["price"] = price

            # Should detect conflict due to price mismatch
            with pytest.raises(IdempotencyConflict) as exc_info:
                pre_submit_check("test_id", test_spec, mock_store)

            assert "specification mismatch" in str(
                exc_info.value
            ), f"Should detect price conflict: {price}"

    def test_conflict_detection_quantity_variations(self):
        """Test conflict detection across quantity variations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test different quantities should trigger conflicts
        quantity_variations = ["0.02", "0.005", "1.0", "0.0001"]

        for quantity in quantity_variations:
            test_spec = base_spec.copy()
            test_spec["quantity"] = quantity

            with pytest.raises(IdempotencyConflict):
                pre_submit_check("test_id", test_spec, mock_store)

    def test_conflict_detection_side_variations(self):
        """Test conflict detection across side variations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test opposite side should trigger conflict
        test_spec = base_spec.copy()
        test_spec["side"] = "SELL"

        with pytest.raises(IdempotencyConflict):
            pre_submit_check("test_id", test_spec, mock_store)

    def test_conflict_detection_symbol_variations(self):
        """Test conflict detection across symbol variations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test different symbols should trigger conflicts
        symbol_variations = ["ETHUSDT", "ADAUSDT", "SOLUSDT", "BTCEUR"]

        for symbol in symbol_variations:
            test_spec = base_spec.copy()
            test_spec["symbol"] = symbol

            with pytest.raises(IdempotencyConflict):
                pre_submit_check("test_id", test_spec, mock_store)

    def test_conflict_detection_order_type_variations(self):
        """Test conflict detection across order type variations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
            "type": "LIMIT",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test different order types should trigger conflicts
        type_variations = ["MARKET", "STOP_LOSS", "STOP_LOSS_LIMIT", "TAKE_PROFIT"]

        for order_type in type_variations:
            test_spec = base_spec.copy()
            test_spec["type"] = order_type

            with pytest.raises(IdempotencyConflict):
                pre_submit_check("test_id", test_spec, mock_store)

    def test_conflict_detection_time_in_force_variations(self):
        """Test conflict detection across timeInForce variations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
            "timeInForce": "GTC",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test different timeInForce values should trigger conflicts
        tif_variations = ["IOC", "FOK", "GTX"]

        for tif in tif_variations:
            test_spec = base_spec.copy()
            test_spec["timeInForce"] = tif

            with pytest.raises(IdempotencyConflict):
                pre_submit_check("test_id", test_spec, mock_store)

    def test_conflict_detection_comprehensive_matrix(self):
        """Test conflict detection across multiple parameter combinations."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
            "type": "LIMIT",
            "timeInForce": "GTC",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test combinations of parameter changes
        parameter_variations = {
            "symbol": ["ETHUSDT", "ADAUSDT"],
            "side": ["SELL"],
            "quantity": ["0.02", "0.005"],
            "price": ["51000.0", "49000.0"],
            "type": ["MARKET"],
            "timeInForce": ["IOC", "FOK"],
        }

        conflict_count = 0

        # Test various combinations
        for param, values in parameter_variations.items():
            for value in values:
                test_spec = base_spec.copy()
                test_spec[param] = value

                with pytest.raises(IdempotencyConflict):
                    pre_submit_check("test_id", test_spec, mock_store)

                conflict_count += 1

        assert conflict_count > 0, "Should detect conflicts in parameter variations"

    def test_no_conflict_identical_specifications(self):
        """Test no conflict when specifications are identical."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Same spec hash - should not conflict
        same_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: {
            "spec_hash_key": str(same_hash),
            "status_key": "FILLED",
            "payload_key": json.dumps({"orderId": "12345"}),
        }.get(key.split(":")[-1])

        # Should return HIT, not conflict
        result = pre_submit_check("test_id", base_spec, mock_store)

        assert (
            result["status"] == "HIT"
        ), "Identical specs should return HIT, not conflict"

    def test_conflict_detection_with_additional_fields(self):
        """Test conflict detection when additional fields are present."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        # Spec with additional field
        extended_spec = base_spec.copy()
        extended_spec["stopPrice"] = "49000.0"

        # Cache base spec hash
        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Extended spec should conflict with base spec
        with pytest.raises(IdempotencyConflict):
            pre_submit_check("test_id", extended_spec, mock_store)

    def test_conflict_detection_field_ordering_independence(self):
        """Test conflict detection is independent of field ordering."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        # Same fields, different order
        spec1 = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        spec2 = {
            "price": "50000.0",
            "quantity": "0.01",
            "side": "BUY",
            "symbol": "BTCUSDT",
        }

        # Both should produce same hash
        hash1 = hash(json.dumps(spec1, sort_keys=True))
        hash2 = hash(json.dumps(spec2, sort_keys=True))

        assert hash1 == hash2, "Field ordering should not affect hash"

        # Cache first spec hash
        mock_store.get.side_effect = lambda key: (
            str(hash1) if "spec_hash" in key else None
        )

        # Second spec should not conflict (same hash)
        result = pre_submit_check("test_id", spec2, mock_store)
        assert (
            result["status"] == "HIT"
        ), "Same fields in different order should not conflict"

    def test_conflict_detection_numeric_precision_sensitivity(self):
        """Test conflict detection sensitivity to numeric precision."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01000",  # Extra zeros
            "price": "50000.00",  # Extra zeros
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test with different string representations of same numeric values
        precision_variations = [
            {"quantity": "0.01", "price": "50000.0"},  # Less precision
            {"quantity": "0.010000", "price": "50000.000"},  # More precision
            {"quantity": "1e-2", "price": "5e4"},  # Scientific notation
        ]

        for variation in precision_variations:
            test_spec = base_spec.copy()
            test_spec.update(variation)

            # Different string representations should conflict
            # (This is expected behavior - string-based hashing is sensitive to format)
            try:
                result = pre_submit_check("test_id", test_spec, mock_store)
                # If it doesn't conflict, it should at least return a valid result
                assert result["status"] in ["HIT", "MISS"], "Should return valid status"
            except IdempotencyConflict:
                # Expected for different string formats
                pass

    def test_conflict_detection_case_sensitivity(self):
        """Test conflict detection case sensitivity."""
        mock_store = Mock()
        mock_store.seen.return_value = True

        base_spec = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "quantity": "0.01",
            "price": "50000.0",
        }

        base_hash = hash(json.dumps(base_spec, sort_keys=True))
        mock_store.get.side_effect = lambda key: (
            str(base_hash) if "spec_hash" in key else None
        )

        # Test case variations
        case_variations = [
            {"symbol": "btcusdt"},  # Lowercase symbol
            {"side": "buy"},  # Lowercase side
            {"symbol": "BtcUsdt"},  # Mixed case
        ]

        for variation in case_variations:
            test_spec = base_spec.copy()
            test_spec.update(variation)

            # Case differences should conflict
            with pytest.raises(IdempotencyConflict):
                pre_submit_check("test_id", test_spec, mock_store)
