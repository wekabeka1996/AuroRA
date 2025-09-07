"""
Tests for core/features/absorption.py
"""
import pytest
import time
import math
from unittest.mock import Mock

# Import the module under test
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from core.features.absorption import (
    AbsorptionStream, _EMA, _State, _sum_trades,
    _test_absorption_metrics, _test_queue_ahead,
    _test_absorption_properties, _test_sell_mo_sensitivity
)
from core.types import Trade, Side, MarketSnapshot


class TestEMA:
    """Test the _EMA helper class."""

    def test_ema_initialization(self):
        """Test EMA initialization."""
        ema = _EMA(half_life_s=2.0)
        assert ema.half_life_s == 2.0
        assert ema.value == 0.0
        assert ema._last_ts is None

    def test_ema_first_update(self):
        """Test first EMA update sets value directly."""
        ema = _EMA(half_life_s=2.0)
        result = ema.update(10.0, 1000.0)
        assert result == 10.0
        assert ema.value == 10.0
        assert ema._last_ts == 1000.0

    def test_ema_subsequent_updates(self):
        """Test EMA updates with exponential smoothing."""
        ema = _EMA(half_life_s=2.0)
        ema.update(10.0, 1000.0)
        result = ema.update(20.0, 1002.0)  # 2 seconds later

        # Calculate expected value manually
        lam = math.log(2.0) / 2.0
        w = math.exp(-lam * 2.0)
        expected = w * 10.0 + (1.0 - w) * 20.0

        assert abs(result - expected) < 1e-10
        assert abs(ema.value - expected) < 1e-10

    def test_ema_zero_half_life(self):
        """Test EMA with zero half-life (should not crash)."""
        ema = _EMA(half_life_s=0.0)
        ema.update(10.0, 1000.0)
        result = ema.update(20.0, 1001.0)
        # With zero half-life, should be close to latest value
        assert result == 20.0

    def test_ema_negative_dt(self):
        """Test EMA with negative time difference."""
        ema = _EMA(half_life_s=2.0)
        ema.update(10.0, 1000.0)
        result = ema.update(20.0, 999.0)  # Time goes backwards
        # Should handle gracefully by treating dt as 0
        assert result == 10.0  # No update due to dt=0


class TestSumTrades:
    """Test the _sum_trades helper function."""

    def test_sum_trades_empty(self):
        """Test summing empty trade list."""
        trades = []
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 0.0

    def test_sum_trades_single_matching(self):
        """Test summing single matching trade."""
        trades = [
            Trade(timestamp=1001.0, price=100.0, size=10.0, side=Side.BUY)
        ]
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 10.0

    def test_sum_trades_single_not_matching_side(self):
        """Test summing single trade with wrong side."""
        trades = [
            Trade(timestamp=1001.0, price=100.0, size=10.0, side=Side.SELL)
        ]
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 0.0

    def test_sum_trades_single_before_ts(self):
        """Test summing single trade before timestamp."""
        trades = [
            Trade(timestamp=999.0, price=100.0, size=10.0, side=Side.BUY)
        ]
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 0.0

    def test_sum_trades_multiple(self):
        """Test summing multiple trades."""
        trades = [
            Trade(timestamp=1001.0, price=100.0, size=10.0, side=Side.BUY),
            Trade(timestamp=1002.0, price=100.0, size=5.0, side=Side.BUY),
            Trade(timestamp=1003.0, price=100.0, size=15.0, side=Side.SELL),
        ]
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 15.0  # 10 + 5

    def test_sum_trades_string_side(self):
        """Test summing trades with string side values."""
        trades = [
            Trade(timestamp=1001.0, price=100.0, size=10.0, side="BUY"),
            Trade(timestamp=1002.0, price=100.0, size=5.0, side=Side.BUY),
        ]
        result = _sum_trades(trades, Side.BUY, 1000.0)
        assert result == 15.0


class TestAbsorptionStream:
    """Test the AbsorptionStream class."""

    def test_initialization(self):
        """Test AbsorptionStream initialization."""
        stream = AbsorptionStream(window_s=5.0, ema_half_life_s=2.0)
        assert stream.window_s == 5.0
        assert stream.hl == 2.0
        assert stream.st.last_ts is None
        assert stream.st.bid_p is None
        assert stream.st.ask_p is None
        assert stream.st.bid_q1 == 0.0
        assert stream.st.ask_q1 == 0.0

    def test_initialization_defaults(self):
        """Test AbsorptionStream with default parameters."""
        stream = AbsorptionStream()
        assert stream.window_s == 5.0
        assert stream.hl == 2.0

    def test_first_update_initializes_state(self):
        """Test that first update initializes state and returns features."""
        stream = AbsorptionStream()

        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[600.0, 400.0],
            ask_volumes_l=[620.0, 380.0],
            trades=()
        )

        features = stream.update(snap)

        # Check state was initialized
        assert stream.st.last_ts == 1000.0
        assert stream.st.bid_p == 100.0
        assert stream.st.ask_p == 100.02
        assert stream.st.bid_q1 == 600.0
        assert stream.st.ask_q1 == 620.0

        # Check features are returned (should be all zeros on first update)
        assert isinstance(features, dict)
        assert "rate_sell_mo_hit_bid" in features

    def test_update_with_trades_and_queue_changes(self):
        """Test update with trades and queue size changes."""
        stream = AbsorptionStream(ema_half_life_s=1.0)

        # First snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[600.0],
            ask_volumes_l=[620.0],
            trades=()
        )
        stream.update(snap1)

        # Second snapshot with trades and queue changes
        trades = [
            Trade(timestamp=1000.5, price=100.0, size=20.0, side=Side.SELL),  # Hit bid
            Trade(timestamp=1000.7, price=100.02, size=15.0, side=Side.BUY),  # Hit ask
        ]
        snap2 = MarketSnapshot(
            timestamp=1001.0,  # 1 second later
            bid_price=100.0,   # Same price
            ask_price=100.02,  # Same price
            bid_volumes_l=[580.0],  # Decreased by 20 (SELL-MO)
            ask_volumes_l=[605.0],  # Decreased by 15 (BUY-MO)
            trades=trades
        )

        features = stream.update(snap2)

        # Check rates are updated
        assert features["rate_sell_mo_hit_bid"] > 0
        assert features["rate_buy_mo_hit_ask"] > 0

        # Check absorption fractions
        assert 0.0 <= features["absorption_frac_bid"] <= 1.0
        assert 0.0 <= features["absorption_frac_ask"] <= 1.0

    def test_update_with_price_change_bid_up(self):
        """Test update when bid price increases."""
        stream = AbsorptionStream()

        # First snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[600.0],
            ask_volumes_l=[620.0],
            trades=()
        )
        stream.update(snap1)

        # Second snapshot with bid price up
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=100.01,  # Bid up
            ask_price=100.02,
            bid_volumes_l=[500.0],  # New size at new price
            ask_volumes_l=[620.0],
            trades=()
        )

        features = stream.update(snap2)

        # Should detect replenishment at bid
        assert features["rate_replenish_bid"] > 0

    def test_update_with_price_change_bid_down(self):
        """Test update when bid price decreases (depletion case)."""
        stream = AbsorptionStream()

        # First snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[600.0],
            ask_volumes_l=[620.0],
            trades=()
        )
        stream.update(snap1)

        # Second snapshot with bid price down (depletion)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=99.99,  # Bid down
            ask_price=100.02,
            bid_volumes_l=[500.0],  # New size at new price
            ask_volumes_l=[620.0],
            trades=()
        )

        features = stream.update(snap2)

        # Should detect depletion at bid (no replenishment)
        assert features["rate_replenish_bid"] == 0.0  # No replenishment when price decreases

    def test_update_with_price_change_ask_up(self):
        """Test update when ask price increases (depletion case)."""
        stream = AbsorptionStream()

        # First snapshot
        snap1 = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[600.0],
            ask_volumes_l=[620.0],
            trades=()
        )
        stream.update(snap1)

        # Second snapshot with ask price up (depletion)
        snap2 = MarketSnapshot(
            timestamp=1001.0,
            bid_price=100.0,
            ask_price=100.03,  # Ask up
            bid_volumes_l=[600.0],
            ask_volumes_l=[500.0],  # New size at new price
            trades=()
        )

        features = stream.update(snap2)

        # Should detect depletion at ask (no replenishment)
        assert features["rate_replenish_ask"] == 0.0  # No replenishment when price increases
        """Test comprehensive features computation."""
        stream = AbsorptionStream()

        # Initialize
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[100.0],
            trades=()
        )
        features = stream.update(snap)

        # Check all expected features are present
        expected_keys = [
            "rate_sell_mo_hit_bid", "rate_buy_mo_hit_ask",
            "rate_cancel_bid", "rate_cancel_ask",
            "rate_replenish_bid", "rate_replenish_ask",
            "absorption_frac_bid", "absorption_frac_ask",
            "resilience_bid", "resilience_ask",
            "pressure_bid", "pressure_ask",
            "ttd_bid_s", "ttd_ask_s"
        ]

        for key in expected_keys:
            assert key in features
            assert isinstance(features[key], (int, float))
            assert math.isfinite(features[key]) or features[key] == float('inf')

    def test_estimate_queue_ahead_buy_side(self):
        """Test queue ahead estimation for buy side."""
        stream = AbsorptionStream()

        # Initialize with some state
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[200.0],
            trades=()
        )
        stream.update(snap)

        # Test buy side
        qa = stream.estimate_queue_ahead(Side.BUY, horizon_s=0.0)
        assert qa == 200.0  # Current ask size

        qa_with_horizon = stream.estimate_queue_ahead(Side.BUY, horizon_s=1.0)
        assert qa_with_horizon >= 200.0  # Should include replenishment

    def test_estimate_queue_ahead_sell_side(self):
        """Test queue ahead estimation for sell side."""
        stream = AbsorptionStream()

        # Initialize with some state
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[150.0],
            ask_volumes_l=[100.0],
            trades=()
        )
        stream.update(snap)

        # Test sell side
        qa = stream.estimate_queue_ahead(Side.SELL, horizon_s=0.0)
        assert qa == 150.0  # Current bid size

    def test_estimate_queue_ahead_string_side(self):
        """Test queue ahead estimation with string side values."""
        stream = AbsorptionStream()

        # Initialize with some state
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[150.0],
            ask_volumes_l=[100.0],
            trades=()
        )
        stream.update(snap)

        # Test with string side
        qa = stream.estimate_queue_ahead("SELL", horizon_s=0.0)
        assert qa == 150.0

    def test_edge_cases_empty_volumes(self):
        """Test handling of empty volume lists."""
        stream = AbsorptionStream()

        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[],  # Empty
            ask_volumes_l=[],  # Empty
            trades=()
        )

        features = stream.update(snap)

        # Should handle gracefully
        assert stream.st.bid_q1 == 0.0
        assert stream.st.ask_q1 == 0.0
        assert features["ttd_bid_s"] == float('inf')
        assert features["ttd_ask_s"] == float('inf')

    def test_ttd_calculation(self):
        """Test TTD calculation with different scenarios."""
        stream = AbsorptionStream()

        # Initialize
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[100.0],
            trades=()
        )
        stream.update(snap)

        # Manually set some rates to test TTD
        stream.sell_mo_rate.value = 10.0  # 10 units/second removal
        stream.replenish_rate_bid.value = 5.0  # 5 units/second replenishment
        stream.buy_mo_rate.value = 8.0
        stream.replenish_rate_ask.value = 3.0

        features = stream._features()

        # TTD = queue_size / (removal_rate - replenish_rate)
        # Bid: 100 / (10 - 5) = 20 seconds
        expected_ttd_bid = 100.0 / (10.0 - 5.0)
        assert abs(features["ttd_bid_s"] - expected_ttd_bid) < 1e-10

        # Ask: 100 / (8 - 3) = 20 seconds
        expected_ttd_ask = 100.0 / (8.0 - 3.0)
        assert abs(features["ttd_ask_s"] - expected_ttd_ask) < 1e-10

    def test_ttd_with_negative_net_removal(self):
        """Test TTD when replenishment exceeds removal."""
        stream = AbsorptionStream()

        # Initialize
        snap = MarketSnapshot(
            timestamp=1000.0,
            bid_price=100.0,
            ask_price=100.02,
            bid_volumes_l=[100.0],
            ask_volumes_l=[100.0],
            trades=()
        )
        stream.update(snap)

        # Set rates where replenishment > removal
        stream.sell_mo_rate.value = 5.0
        stream.replenish_rate_bid.value = 10.0  # Replenishment > removal

        features = stream._features()

        # Should be infinite when replenishment >= removal
        assert features["ttd_bid_s"] == float('inf')


class TestSelfTests:
    """Test the existing self-test functions."""

    def test_self_test_absorption_metrics(self):
        """Test that the self-test function runs without error."""
        # Should not raise any exceptions
        _test_absorption_metrics()

    def test_self_test_queue_ahead(self):
        """Test that the queue ahead self-test runs without error."""
        _test_queue_ahead()

    def test_self_test_absorption_properties(self):
        """Test that the properties self-test runs without error."""
        _test_absorption_properties()

    def test_self_test_sell_mo_sensitivity(self):
        """Test that the sensitivity self-test runs without error."""
        _test_sell_mo_sensitivity()


class TestIntegration:
    """Integration tests for the absorption module."""

    def test_full_workflow(self):
        """Test a complete workflow from initialization to feature extraction."""
        # Create stream
        stream = AbsorptionStream(window_s=5.0, ema_half_life_s=2.0)

        # Create a series of snapshots
        snapshots = []
        base_time = time.time()

        for i in range(10):
            trades = []
            if i > 0:  # Add some trades after first snapshot
                trades.append(Trade(
                    timestamp=base_time + i * 0.1,
                    price=100.0 if i % 2 == 0 else 100.02,
                    size=10.0,
                    side=Side.SELL if i % 2 == 0 else Side.BUY
                ))

            snap = MarketSnapshot(
                timestamp=base_time + i * 0.1,
                bid_price=100.0,
                ask_price=100.02,
                bid_volumes_l=[max(50.0, 100.0 - i * 5.0)],  # Decreasing queue
                ask_volumes_l=[max(50.0, 100.0 - i * 3.0)],  # Decreasing queue
                trades=tuple(trades)
            )
            snapshots.append(snap)

        # Process all snapshots
        final_features = None
        for snap in snapshots:
            final_features = stream.update(snap)

        # Verify final features
        assert final_features is not None
        assert all(key in final_features for key in [
            "rate_sell_mo_hit_bid", "absorption_frac_bid", "ttd_bid_s"
        ])

        # All rates should be non-negative
        rate_keys = [k for k in final_features.keys() if k.startswith("rate_")]
        for key in rate_keys:
            assert final_features[key] >= 0

    def test_memory_efficiency(self):
        """Test that the stream doesn't grow memory unbounded."""
        stream = AbsorptionStream()

        # Process many snapshots
        base_time = time.time()
        for i in range(1000):
            snap = MarketSnapshot(
                timestamp=base_time + i * 0.01,
                bid_price=100.0,
                ask_price=100.02,
                bid_volumes_l=[100.0],
                ask_volumes_l=[100.0],
                trades=()
            )
            stream.update(snap)

        # The stream should maintain bounded state (no growing collections)
        # This is a simple check - in practice we'd monitor memory usage
        assert stream.st.last_ts is not None
        assert stream.st.bid_p is not None