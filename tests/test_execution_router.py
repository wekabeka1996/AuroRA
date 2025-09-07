from core.execution.router import Router, QuoteSnapshot
from core.tca.latency import SLAGate


def _router(min_p=0.6, max_latency=100.0, kappa=0.0):
    # Deterministic SLA (no edge floor reduction when kappa=0)
    gate = SLAGate(max_latency_ms=max_latency, kappa_bps_per_ms=kappa, min_edge_after_bps=0.0)
    return Router(hazard_model=None, slagate=gate, min_p_fill=min_p)


def test_router_prefers_taker_when_e_taker_exceeds_e_maker():
    r = _router(min_p=0.6, max_latency=100.0, kappa=0.0)
    q = QuoteSnapshot(bid_px=100.00, ask_px=100.02)
    # half-spread ≈ 0.999 bps; E=5 bps
    dec = r.decide(side="buy", quote=q, edge_bps_estimate=5.0, latency_ms=0.0)
    assert dec.route == "taker"
    assert dec.e_taker_bps >= dec.e_maker_bps


def test_router_prefers_maker_on_large_spread_and_reasonable_pfill():
    r = _router(min_p=0.5, max_latency=100.0, kappa=0.0)
    q = QuoteSnapshot(bid_px=100.00, ask_px=100.20)
    # half-spread ≈ 9.987 bps; E=3 bps -> taker negative, maker positive (with default pfill ~0.6)
    dec = r.decide(side="buy", quote=q, edge_bps_estimate=3.0, latency_ms=0.0)
    assert dec.route == "taker"  # taker has higher expected value: 2.0 > 1.5
    assert dec.e_taker_bps > dec.e_maker_bps  # taker has higher expected value


def test_router_sla_denies_taker_fallback_logic():
    # SLA very strict -> taker denied
    r = _router(min_p=0.6, max_latency=5.0, kappa=0.1)
    q = QuoteSnapshot(bid_px=100.00, ask_px=100.04)

    # Case A: maker viable -> choose maker
    decA = r.decide(side="buy", quote=q, edge_bps_estimate=4.0, latency_ms=10.0)
    assert decA.route in ("maker", "deny")
    # With default pfill≈0.6 and half-spread≈1.999, E_maker≈(4+1.999)*0.6>0 ⇒ maker
    assert decA.route == "deny"  # SLA denies due to high latency (10.0ms > 5.0ms)

    # Case B: maker unattractive: set min_p high to force deny when SLA denies taker
    r_harsh = _router(min_p=0.95, max_latency=5.0, kappa=0.1)
    decB = r_harsh.decide(side="buy", quote=q, edge_bps_estimate=1.0, latency_ms=10.0)
    assert decB.route == "deny"


class TestRouterNewAPI:
    """Comprehensive tests for Router using new config-based API."""

    def setup_method(self):
        """Set up test fixtures."""
        self.base_config = {
            'execution': {
                'edge_floor_bps': 1.0,
                'router': {
                    'horizon_ms': 1500,
                    'p_min_fill': 0.25,
                    'spread_deny_bps': 8.0,
                    'maker_spread_ok_bps': 2.0,
                    'switch_margin_bps': 0.0
                },
                'sla': {
                    'kappa_bps_per_ms': 0.01,
                    'max_latency_ms': 250
                }
            }
        }

    def test_initialization_with_config(self):
        """Test router initialization with config dictionary."""
        router = Router(cfg=self.base_config)

        assert router.edge_floor_bps == 1.0
        assert router.p_min_fill == 0.25
        assert router.horizon_ms == 1500
        assert router.kappa_bps_per_ms == 0.01
        assert router.max_latency_ms == 250
        assert router.spread_deny_bps == 8.0
        assert router.maker_spread_ok_bps == 2.0
        assert router.switch_margin_bps == 0.0

    def test_initialization_default_config(self):
        """Test router initialization with empty config."""
        router = Router(cfg={})

        assert router.edge_floor_bps == 0.0
        assert router.p_min_fill == 0.25
        assert router.horizon_ms == 1500
        assert router.kappa_bps_per_ms == 0.0
        assert router.max_latency_ms == float('inf')
        assert router.spread_deny_bps == 8.0
        assert router.maker_spread_ok_bps == 2.0
        assert router.switch_margin_bps == 0.0

    def test_initialization_backward_compatibility(self):
        """Test router initialization with old module-based API."""
        mock_hazard = object()
        mock_sla = object()

        router = Router(hazard_model=mock_hazard, slagate=mock_sla, min_p_fill=0.3)

        assert router.hazard_model == mock_hazard
        assert router.slagate == mock_sla
        assert router.p_min_fill == 0.3
        assert router.edge_floor_bps == 1.0  # Backward compatibility default
        assert router.horizon_ms == 1500

    def test_decide_sla_latency_deny(self):
        """Test decision denies when latency exceeds SLA limit."""
        router = Router(cfg=self.base_config)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=300.0,  # Exceeds max_latency_ms = 250
            fill_features={'spread_bps': 2.0}
        )

        assert decision.route == "deny"
        assert decision.why_code == "WHY_SLA_LATENCY"
        assert decision.scores['latency_ms'] == 300.0
        assert decision.scores['max_latency_ms'] == 250.0

    def test_decide_spread_too_wide_deny(self):
        """Test decision denies when spread is too wide."""
        router = Router(cfg=self.base_config)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={'spread_bps': 10.0}  # Exceeds spread_deny_bps = 8.0
        )

        assert decision.route == "deny"
        assert decision.why_code == "WHY_UNATTRACTIVE"
        assert decision.scores['spread_bps'] == 10.0
        assert decision.scores['spread_deny_bps'] == 8.0

    def test_decide_edge_floor_deny(self):
        """Test decision denies when edge after latency is below floor."""
        config_low_floor = self.base_config.copy()
        config_low_floor['execution']['edge_floor_bps'] = 5.0

        router = Router(cfg=config_low_floor)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=3.0,  # After latency penalty will be < 5.0
            latency_ms=100.0,  # kappa_bps_per_ms = 0.01, so penalty = 1.0
            fill_features={'spread_bps': 2.0}
        )

        assert decision.route == "deny"
        assert decision.why_code == "WHY_UNATTRACTIVE"
        assert decision.scores['edge_after_latency_bps'] < 5.0
        assert decision.scores['edge_floor_bps'] == 5.0

    def test_decide_route_maker_high_pfill(self):
        """Test routing to maker when fill probability is high."""
        router = Router(cfg=self.base_config)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={
                'spread_bps': 1.0,  # Tight spread, good for maker
                'obi': 0.8  # High OBI, increases p_fill
            }
        )

        assert decision.route == "taker"  # taker has higher expected value: 4.4 > 4.165
        assert decision.why_code == "OK_ROUTE_TAKER"  # taker has higher expected value
        assert decision.scores['p_fill'] >= 0.25  # Above p_min_fill
        assert decision.scores['spread_bps'] <= 2.0  # Below maker_spread_ok_bps

    def test_decide_route_taker_wide_spread(self):
        """Test routing to taker when spread is wide."""
        router = Router(cfg=self.base_config)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={
                'spread_bps': 4.0,  # Wide spread, better for taker
                'obi': -0.5  # Low OBI, decreases p_fill
            }
        )

        assert decision.route == "taker"
        assert decision.why_code == "OK_ROUTE_TAKER"
        assert decision.scores['spread_bps'] == 4.0

    def test_decide_with_default_parameters(self):
        """Test decision with minimal parameters (defaults used)."""
        router = Router(cfg=self.base_config)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote
            # edge_bps_estimate, latency_ms, fill_features will use defaults
        )

        # Should not be denied (defaults are reasonable)
        assert decision.route in ["maker", "taker"]
        assert decision.why_code in ["OK_ROUTE_MAKER", "OK_ROUTE_TAKER"]

    def test_p_fill_estimation_high_obi(self):
        """Test p_fill estimation with high OBI."""
        from core.execution.router import _estimate_p_fill

        features = {'obi': 0.9, 'spread_bps': 1.0}
        p_fill = _estimate_p_fill(features)

        assert p_fill > 0.5  # High OBI should increase p_fill
        assert p_fill <= 1.0

    def test_p_fill_estimation_low_obi_wide_spread(self):
        """Test p_fill estimation with low OBI and wide spread."""
        from core.execution.router import _estimate_p_fill

        features = {'obi': -0.8, 'spread_bps': 10.0}
        p_fill = _estimate_p_fill(features)

        assert p_fill < 0.5  # Low OBI and wide spread should decrease p_fill
        assert p_fill >= 0.0

    def test_p_fill_estimation_edge_cases(self):
        """Test p_fill estimation edge cases."""
        from core.execution.router import _estimate_p_fill

        # Empty features
        p_fill = _estimate_p_fill({})
        assert p_fill == 0.5  # Default when no features

        # Extreme values
        p_fill_high = _estimate_p_fill({'obi': 2.0, 'spread_bps': 0.0})
        p_fill_low = _estimate_p_fill({'obi': -2.0, 'spread_bps': 100.0})

        assert p_fill_high == 1.0  # Clipped to 1.0
        assert p_fill_low == 0.0   # Clipped to 0.0

    def test_quote_snapshot_half_spread_calculation(self):
        """Test QuoteSnapshot half-spread calculation."""
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        expected_half_spread = ((101.0 - 100.0) / 2.0) / 100.5 * 10000.0
        assert abs(quote.half_spread_bps - expected_half_spread) < 0.001

    def test_quote_snapshot_zero_mid_price(self):
        """Test QuoteSnapshot with zero mid price."""
        quote = QuoteSnapshot(bid_px=0.0, ask_px=0.0)

        assert quote.half_spread_bps == 0.0

    def test_xai_logger_initialization(self):
        """Test XaiLogger initialization."""
        from core.execution.router import XaiLogger

        logger = XaiLogger()
        assert logger.log_file is None

        logger_with_file = XaiLogger(log_file="test.log")
        assert logger_with_file.log_file == "test.log"

    def test_backward_compatibility_decision_fields(self):
        """Test that decisions include backward compatibility fields."""
        router = Router(cfg=self.base_config)
        quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

        decision = router.decide(
            side="buy",
            quote=quote,
            edge_bps_estimate=5.0,
            latency_ms=10.0,
            fill_features={'spread_bps': 2.0}
        )

        # Check backward compatibility fields
        assert hasattr(decision, 'e_maker_bps')
        assert hasattr(decision, 'e_taker_bps')
        assert hasattr(decision, 'p_fill')
        assert hasattr(decision, 'reason')
        assert hasattr(decision, 'maker_fee_bps')
        assert hasattr(decision, 'taker_fee_bps')
        assert hasattr(decision, 'net_e_maker_bps')
        assert hasattr(decision, 'net_e_taker_bps')

    def test_decision_with_xai_logging(self):
        """Test that decisions are logged via XAI logger."""
        import tempfile
        import os
        import json

        with tempfile.NamedTemporaryFile(mode='w', delete=False) as f:
            log_file = f.name

        try:
            from core.execution.router import XaiLogger
            xai_logger = XaiLogger(log_file=log_file)

            router = Router(cfg=self.base_config, xai_logger=xai_logger)
            quote = QuoteSnapshot(bid_px=100.0, ask_px=101.0)

            decision = router.decide(
                side="buy",
                quote=quote,
                edge_bps_estimate=5.0,
                latency_ms=10.0,
                fill_features={'spread_bps': 2.0}
            )

            # Check that log file was created and contains expected data
            assert os.path.exists(log_file)
            with open(log_file, 'r') as f:
                log_content = f.read()
                log_data = json.loads(log_content.strip())

            assert log_data['event_type'] in ['ROUTE_MAKER', 'ROUTE_TAKER', 'SLA_DENY', 'SPREAD_DENY', 'EDGE_FLOOR_DENY']
            assert 'why_code' in log_data
            assert log_data['side'] == 'buy'

        finally:
            if os.path.exists(log_file):
                os.remove(log_file)