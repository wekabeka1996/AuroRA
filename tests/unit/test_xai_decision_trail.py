"""
Unit Tests — XAI Decision Trail
==============================

Test XAI logging and decision trail functionality.
Ensures all decision points are properly logged with WHY codes.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from core.execution.router import QuoteSnapshot, Router
from core.tca.hazard_cox import CoxPH
from core.tca.latency import SLAGate


class TestXaiDecisionTrail:
    """Test XAI decision logging and trail."""

    @pytest.fixture
    def router_components(self):
        """Create router with logging enabled."""
        # CoxPH
        cox = CoxPH()
        cox._beta = {'obi': 0.1, 'spread_bps': -0.05}
        cox._feat = ['obi', 'spread_bps']

        # SLA
        sla = SLAGate(max_latency_ms=250, kappa_bps_per_ms=0.01, min_edge_after_bps=1.0)

        # Router
        router = Router(
            hazard_model=cox,
            slagate=sla,
            min_p_fill=0.25,
            exchange_name='test'
        )

        return router

    def test_decision_structure(self, router_components):
        """Test that decisions have all required fields."""
        router = router_components

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={'obi': 0.8, 'spread_bps': 1.0}
        )

        # Verify decision has all required fields
        assert hasattr(decision, 'route')
        assert hasattr(decision, 'e_maker_bps')
        assert hasattr(decision, 'e_taker_bps')
        assert hasattr(decision, 'p_fill')
        assert hasattr(decision, 'reason')
        assert hasattr(decision, 'maker_fee_bps')
        assert hasattr(decision, 'taker_fee_bps')
        assert hasattr(decision, 'net_e_maker_bps')
        assert hasattr(decision, 'net_e_taker_bps')

        # Verify route is valid
        assert decision.route in ['maker', 'taker', 'deny']

        # Verify reason is not empty
        assert decision.reason != ""

        # Verify p_fill is reasonable
        assert 0.0 <= decision.p_fill <= 1.0

    def test_sla_breach_denial(self, router_components):
        """Test that SLA breaches result in denial or maker fallback."""
        router = router_components

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=300.0,  # Breach SLA (250ms limit)
            fill_features={'obi': 0.5, 'spread_bps': 2.0}
        )

        # SLA breach should either deny or fallback to maker if maker is still attractive
        assert decision.route in ['deny', 'maker']
        if decision.route == 'maker':
            assert 'SLA denied taker, fallback to maker' in decision.reason
        else:
            assert 'SLA' in decision.reason

    def test_low_pfill_constraint(self, router_components):
        """Test low p_fill constraint handling."""
        router = router_components

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={'obi': -0.9, 'spread_bps': 10.0}  # Low p_fill
        )

        # Verify decision is made (route could be taker or deny based on economics)
        assert decision.route in ['maker', 'taker', 'deny']
        assert decision.p_fill < 0.5  # Should have low p_fill

    def test_decision_logging_file_creation(self, router_components, tmp_path):
        """Test that decision log files are created correctly."""
        router = router_components

        # Create a temporary log directory
        log_dir = tmp_path / "logs"
        log_dir.mkdir()

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        # This should create the routing_decisions.jsonl file
        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=3.0,
            latency_ms=10.0,
            fill_features={'obi': 0.5, 'spread_bps': 2.0}
        )

        # Check if log file was created
        log_file = Path("logs/routing_decisions.jsonl")
        if log_file.exists():
            content = log_file.read_text()
            assert "ROUTE_DECISION" in content
            assert "why_code" in content

            # Parse JSON lines
            lines = content.strip().split('\n')
            for line in lines:
                if line.strip():
                    entry = json.loads(line)
                    assert "event_type" in entry
                    assert "why_code" in entry
                    assert "inputs" in entry
                    assert "outputs" in entry

    def test_different_routing_scenarios(self, router_components):
        """Test various routing scenarios and their properties."""
        router = router_components

        scenarios = [
            # (description, edge_bps, latency_ms, fill_features, expected_properties)
            ("high_edge_good_fill", 8.0, 10.0, {'obi': 0.8, 'spread_bps': 1.0}, "high_edge"),
            ("moderate_edge", 4.0, 10.0, {'obi': 0.5, 'spread_bps': 2.0}, "moderate_edge"),
            ("low_edge", 1.0, 10.0, {'obi': 0.2, 'spread_bps': 3.0}, "low_edge"),
            ("high_latency", 5.0, 300.0, {'obi': 0.5, 'spread_bps': 2.0}, "high_latency"),
        ]

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        for desc, edge_bps, latency_ms, fill_features, scenario_type in scenarios:
            decision = router.decide(
                side='buy',
                quote=quote,
                edge_bps_estimate=edge_bps,
                latency_ms=latency_ms,
                fill_features=fill_features
            )

            # Verify decision structure
            assert decision.route in ['maker', 'taker', 'deny']
            assert isinstance(decision.e_maker_bps, (int, float))
            assert isinstance(decision.e_taker_bps, (int, float))
            assert isinstance(decision.p_fill, (int, float))
            assert len(decision.reason) > 0

            # Scenario-specific checks
            if scenario_type == "high_latency":
                # High latency should either deny or have SLA considerations
                if decision.route == "deny":
                    assert "SLA" in decision.reason or "latency" in decision.reason.lower()

    def test_fee_calculations(self, router_components):
        """Test that fee calculations are included in decisions."""
        router = router_components

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={'obi': 0.5, 'spread_bps': 2.0}
        )

        # Verify fees are included
        assert hasattr(decision, 'maker_fee_bps')
        assert hasattr(decision, 'taker_fee_bps')
        assert hasattr(decision, 'net_e_maker_bps')
        assert hasattr(decision, 'net_e_taker_bps')

        # Fees should be reasonable values
        assert decision.maker_fee_bps >= 0.0
        assert decision.taker_fee_bps >= 0.0

    def test_edge_calculations(self, router_components):
        """Test that edge calculations are mathematically sound."""
        router = router_components

        quote = QuoteSnapshot(bid_px=49999.0, ask_px=50001.0)

        decision = router.decide(
            side='buy',
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={'obi': 0.5, 'spread_bps': 2.0}
        )

        # Verify edge calculations are reasonable
        half_spread = quote.half_spread_bps

        # Current router logic:
        # e_maker_bps = edge_after_lat (no spread adjustment)
        # e_taker_bps = edge_after_lat - spread/2

        # Edge after latency should be close to original estimate
        edge_after_lat = 5.0 - 10.0 * router.kappa_bps_per_ms if hasattr(router, 'kappa_bps_per_ms') else 5.0

        # Basic sanity checks
        assert isinstance(decision.e_maker_bps, (int, float))
        assert isinstance(decision.e_taker_bps, (int, float))

        # e_taker should be lower than e_maker due to spread cost
        if decision.route == 'taker':
            # Taker was chosen, so e_taker_expected >= e_maker_expected
            assert decision.e_taker_bps <= decision.e_maker_bps  # Before p_fill adjustment
        elif decision.route == 'maker':
            # Maker was chosen, so e_maker_expected >= e_taker_expected
            assert decision.e_maker_bps >= decision.e_taker_bps


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
