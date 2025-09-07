"""
Comprehensive test suite for core/features/obi.py
Tests all functions, edge cases, and streaming functionality.
"""
import pytest
from decimal import Decimal
from unittest.mock import Mock, patch

from core.features.obi import (
    depth_sums,
    depth_ratio,
    obi_l1,
    obi_lk,
    spread_bps,
    OBIStream
)
from core.types import MarketSnapshot


class TestOBIFunctions:
    """Test pure OBI calculation functions."""

    def test_depth_sums_basic(self):
        """Test basic depth sums calculation."""
        bid_volumes = [10.0, 8.0, 6.0]
        ask_volumes = [12.0, 9.0, 7.0]

        bid_sum, ask_sum = depth_sums(bid_volumes, ask_volumes, levels=2)
        assert bid_sum == 18.0  # 10 + 8
        assert ask_sum == 21.0  # 12 + 9

    def test_depth_sums_empty_lists(self):
        """Test depth sums with empty lists."""
        bid_sum, ask_sum = depth_sums([], [], levels=5)
        assert bid_sum == 0.0
        assert ask_sum == 0.0

    def test_depth_sums_levels_clamping(self):
        """Test depth sums with levels exceeding list length."""
        bid_volumes = [10.0]
        ask_volumes = [12.0]

        bid_sum, ask_sum = depth_sums(bid_volumes, ask_volumes, levels=5)
        assert bid_sum == 10.0
        assert ask_sum == 12.0

    def test_depth_ratio_basic(self):
        """Test basic depth ratio calculation."""
        bid_volumes = [10.0, 8.0]
        ask_volumes = [12.0, 9.0]

        ratio = depth_ratio(bid_volumes, ask_volumes, levels=2)
        expected = (10.0 + 8.0) / (12.0 + 9.0 + 10.0 + 8.0)  # bid / total
        assert abs(ratio - expected) < 1e-12

    def test_depth_ratio_zero_total(self):
        """Test depth ratio with zero total volume."""
        ratio = depth_ratio([], [], levels=5)
        assert ratio == 0.0

    def test_obi_l1_basic(self):
        """Test L1 OBI calculation."""
        bid_volumes = [10.0, 8.0]
        ask_volumes = [12.0, 9.0]

        obi = obi_l1(bid_volumes, ask_volumes)
        expected = (10.0 - 12.0) / (10.0 + 12.0)  # (bid1 - ask1) / (bid1 + ask1)
        assert abs(obi - expected) < 1e-12

    def test_obi_l1_empty_lists(self):
        """Test L1 OBI with empty lists."""
        obi = obi_l1([], [])
        assert obi == 0.0

    def test_obi_l1_zero_denominator(self):
        """Test L1 OBI with zero denominator."""
        bid_volumes = [0.0]
        ask_volumes = [0.0]

        obi = obi_l1(bid_volumes, ask_volumes)
        assert obi == 0.0

    def test_obi_lk_basic(self):
        """Test Lk OBI calculation."""
        bid_volumes = [10.0, 8.0, 6.0]
        ask_volumes = [12.0, 9.0, 7.0]

        obi = obi_lk(bid_volumes, ask_volumes, levels=2)
        bid_sum = 10.0 + 8.0
        ask_sum = 12.0 + 9.0
        expected = (bid_sum - ask_sum) / (bid_sum + ask_sum)
        assert abs(obi - expected) < 1e-12

    def test_obi_lk_zero_denominator(self):
        """Test Lk OBI with zero denominator."""
        obi = obi_lk([], [], levels=5)
        assert obi == 0.0

    def test_spread_bps_basic(self):
        """Test spread BPS calculation."""
        bid_price = 100.0
        ask_price = 100.02

        bps = spread_bps(bid_price, ask_price)
        expected = 1e4 * (0.02) / 100.01  # 2 bps
        assert abs(bps - expected) < 1e-12

    def test_spread_bps_zero_mid(self):
        """Test spread BPS with zero mid price."""
        bps = spread_bps(0.0, 0.0)
        assert bps == 0.0


class TestOBIStream:
    """Test OBIStream streaming functionality."""

    def test_initialization(self):
        """Test OBIStream initialization."""
        stream = OBIStream(levels=5)
        assert stream.levels == 5

    def test_initialization_levels_clamping(self):
        """Test levels clamping in initialization."""
        stream = OBIStream(levels=0)
        assert stream.levels == 1

    def test_update_basic(self):
        """Test basic update functionality."""
        stream = OBIStream(levels=3)

        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0, 6.0, 4.0],
            ask_volumes_l=[12.0, 9.0, 7.0, 5.0]
        )

        features = stream.update(snapshot)

        # Check all expected features are present
        expected_keys = [
            "mid", "spread", "spread_bps", "depth_bid_lk", "depth_ask_lk",
            "depth_ratio", "obi_l1", "obi_lk"
        ]
        for key in expected_keys:
            assert key in features

        # Check mid price
        assert abs(features["mid"] - 100.0) < 1e-12

        # Check spread
        assert abs(features["spread"] - 0.04) < 1e-12

        # Check OBI ranges
        assert -1.0 <= features["obi_l1"] <= 1.0
        assert -1.0 <= features["obi_lk"] <= 1.0

        # Check depth sums
        assert features["depth_bid_lk"] == 10.0 + 8.0 + 6.0  # levels=3
        assert features["depth_ask_lk"] == 12.0 + 9.0 + 7.0

    def test_update_empty_volumes(self):
        """Test update with empty volume lists."""
        stream = OBIStream(levels=5)

        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[],
            ask_volumes_l=[]
        )

        features = stream.update(snapshot)

        assert features["depth_bid_lk"] == 0.0
        assert features["depth_ask_lk"] == 0.0
        assert features["depth_ratio"] == 0.0
        assert features["obi_l1"] == 0.0
        assert features["obi_lk"] == 0.0

    def test_update_single_level(self):
        """Test update with single level."""
        stream = OBIStream(levels=1)

        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0],
            ask_volumes_l=[12.0, 9.0]
        )

        features = stream.update(snapshot)

        # With levels=1, should only use first level
        assert features["depth_bid_lk"] == 10.0
        assert features["depth_ask_lk"] == 12.0

        # OBI L1 should equal OBI Lk with levels=1
        assert abs(features["obi_l1"] - features["obi_lk"]) < 1e-12

    def test_multiple_updates(self):
        """Test multiple updates maintain consistency."""
        stream = OBIStream(levels=3)

        # First snapshot
        snapshot1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=99.98,
            ask_price=100.02,
            bid_volumes_l=[10.0, 8.0, 6.0],
            ask_volumes_l=[12.0, 9.0, 7.0]
        )

        features1 = stream.update(snapshot1)

        # Second snapshot with different volumes and prices
        snapshot2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=100.95,  # Different bid price to ensure different mid
            ask_price=101.05,  # Different ask price to ensure different mid
            bid_volumes_l=[15.0, 12.0, 9.0],
            ask_volumes_l=[18.0, 14.0, 10.0]
        )

        features2 = stream.update(snapshot2)

        # Features should be different
        assert features1["depth_bid_lk"] != features2["depth_bid_lk"]
        assert features1["mid"] != features2["mid"]  # Now these should be different

        # But all features should still be valid
        for features in [features1, features2]:
            assert -1.0 <= features["obi_l1"] <= 1.0
            assert -1.0 <= features["obi_lk"] <= 1.0
            assert features["depth_ratio"] >= 0.0
            assert features["spread_bps"] >= 0.0

    def test_spread_bps_calculation(self):
        """Test spread BPS calculation in stream."""
        stream = OBIStream()

        snapshot = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.05,  # 5 bps spread
            bid_volumes_l=[10.0],
            ask_volumes_l=[10.0]
        )

        features = stream.update(snapshot)

        expected_bps = 1e4 * 0.05 / 100.025  # spread / mid * 10000
        assert abs(features["spread_bps"] - expected_bps) < 1e-12


class TestOBIEdgeCases:
    """Test edge cases and error conditions."""

    def test_very_small_volumes(self):
        """Test with very small volume values."""
        bid_volumes = [1e-9, 1e-10]
        ask_volumes = [1e-9, 1e-10]

        obi = obi_lk(bid_volumes, ask_volumes, levels=2)
        assert -1.0 <= obi <= 1.0

        ratio = depth_ratio(bid_volumes, ask_volumes, levels=2)
        assert 0.0 <= ratio <= 1.0

    def test_very_large_volumes(self):
        """Test with very large volume values."""
        bid_volumes = [1e9, 1e8]
        ask_volumes = [1e9, 1e8]

        obi = obi_lk(bid_volumes, ask_volumes, levels=2)
        assert -1.0 <= obi <= 1.0

        ratio = depth_ratio(bid_volumes, ask_volumes, levels=2)
        assert 0.0 <= ratio <= 1.0

    def test_mixed_empty_and_nonempty(self):
        """Test with one empty and one non-empty volume list."""
        bid_volumes = [10.0, 8.0]
        ask_volumes = []

        obi = obi_l1(bid_volumes, ask_volumes)
        assert obi == 1.0  # Maximum imbalance favoring bids when ask is empty

    def test_negative_prices(self):
        """Test with negative prices (edge case)."""
        # This shouldn't happen in real markets but test robustness
        bps = spread_bps(-100.0, -99.98)
        assert bps == 0.0  # Should return 0 for invalid prices

    def test_identical_prices(self):
        """Test with identical bid/ask prices."""
        bps = spread_bps(100.0, 100.0)
        assert bps == 0.0

    def test_extreme_spread(self):
        """Test with extreme spread values."""
        bps = spread_bps(100.0, 200.0)  # 100% spread
        expected = 1e4 * 100.0 / 150.0  # spread / mid * 10000
        assert abs(bps - expected) < 1e-12


class TestOBISelfTests:
    """Test the self-test functions to achieve 100% coverage."""

    def test_mock_snapseq(self):
        """Test the _mock_snapseq function."""
        from core.features.obi import _mock_snapseq

        snaps = _mock_snapseq()

        # Should generate 20 snapshots
        assert len(snaps) == 20

        # All snapshots should have valid data
        for snap in snaps:
            assert snap.timestamp > 0
            assert snap.bid_price > 0
            assert snap.ask_price > snap.bid_price  # ask > bid
            assert len(snap.bid_volumes_l) == 5
            assert len(snap.ask_volumes_l) == 5
            assert all(v > 0 for v in snap.bid_volumes_l)
            assert all(v > 0 for v in snap.ask_volumes_l)

    def test_test_pure_funcs(self):
        """Test the _test_pure_funcs function."""
        from core.features.obi import _test_pure_funcs

        # Should not raise any exceptions
        _test_pure_funcs()

    def test_test_stream(self):
        """Test the _test_stream function."""
        from core.features.obi import _test_stream

        # Should not raise any exceptions
        _test_stream()

    def test_main_block_execution(self):
        """Test execution of the main block by running the module as a script."""
        import runpy
        import sys
        from io import StringIO
        from unittest.mock import patch

        # Capture stdout to verify the print statement
        captured_output = StringIO()

        with patch('sys.stdout', captured_output):
            # Run the module as a script
            runpy.run_module('core.features.obi', run_name='__main__')

        # Verify the success message was printed
        output = captured_output.getvalue()
        assert "OK - repo/core/features/obi.py self-tests passed" in output