"""
Unit Tests — Router v1.1 Decision Logic
======================================

Tests for Router v1.1 with Decision interface, SLA gates, edge_floor after latency,
and WHY codes for XAI tracing.
"""

import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy router v1.1 decision logic; superseded by router_v2; quarantined"
    ),
]

from core.execution.router import Decision, Router

BASE_CFG = {
    "execution": {
        "edge_floor_bps": 1.0,
        "router": {
            "horizon_ms": 1500,
            "p_min_fill": 0.25,
            "spread_deny_bps": 8.0,
            "maker_spread_ok_bps": 2.0,
        },
        "sla": {"kappa_bps_per_ms": 0.01, "max_latency_ms": 250},
    }
}


def make_router():
    return Router(BASE_CFG)


def test_high_pfill_tight_spread_maker():
    """Test maker route with high P(fill) and tight spread."""
    r = make_router()
    q = type("Q", (), {"bid_px": 49999.0, "ask_px": 50001.0})
    d = r.decide(
        "buy",
        q,
        edge_bps_estimate=5.0,
        latency_ms=10.0,
        fill_features={"obi": 0.8, "spread_bps": 1.0},
    )
    assert d.route == "maker" and d.why_code == "OK_ROUTE_MAKER"
    assert "p_fill" in d.scores
    assert d.scores["p_fill"] > 0.5


def test_low_pfill_wide_spread_taker():
    """Test taker route with low P(fill) and wide spread."""
    r = make_router()
    q = type("Q", (), {"bid_px": 49995.0, "ask_px": 50005.0})
    d = r.decide(
        "buy",
        q,
        edge_bps_estimate=2.0,
        latency_ms=10.0,
        fill_features={"obi": -0.8, "spread_bps": 5.0},
    )
    assert d.route == "taker" and d.why_code == "OK_ROUTE_TAKER"
    assert "p_fill" in d.scores
    assert d.scores["p_fill"] < 0.5


def test_sla_denies_on_high_latency():
    """Test SLA denial on excessive latency."""
    r = make_router()
    q = type("Q", (), {"bid_px": 49999.0, "ask_px": 50001.0})
    d = r.decide(
        "buy",
        q,
        edge_bps_estimate=5.0,
        latency_ms=300.0,
        fill_features={"obi": 0.5, "spread_bps": 2.0},
    )
    assert d.route == "deny" and d.why_code == "WHY_SLA_LATENCY"
    assert "latency_ms" in d.scores
    assert "max_latency_ms" in d.scores


def test_edge_floor_after_latency():
    """Test edge floor gate after latency penalty."""
    r = make_router()
    q = type("Q", (), {"bid_px": 49999.0, "ask_px": 50001.0})
    # edge 0.5 - kappa(0.01)*latency(100) = -0.5 < edge_floor 1.0 => deny
    d = r.decide(
        "buy",
        q,
        edge_bps_estimate=0.5,
        latency_ms=100.0,
        fill_features={"obi": 0.1, "spread_bps": 1.0},
    )
    assert d.route == "deny" and d.why_code == "WHY_UNATTRACTIVE"
    assert "edge_after_latency_bps" in d.scores
    assert "edge_floor_bps" in d.scores


def test_why_unattractive_on_very_wide_spread():
    """Test denial on very wide spread."""
    r = make_router()
    q = type("Q", (), {"bid_px": 49999.0, "ask_px": 50001.0})
    d = r.decide(
        "buy",
        q,
        edge_bps_estimate=3.0,
        latency_ms=10.0,
        fill_features={"obi": 0.0, "spread_bps": 10.0},
    )
    assert d.route == "deny" and d.why_code == "WHY_UNATTRACTIVE"
    assert "spread_bps" in d.scores
    assert "spread_deny_bps" in d.scores


def test_scores_present_for_xai():
    """Test that scores are present for XAI tracing."""
    r = make_router()
    q = type("Q", (), {"bid_px": 49999.0, "ask_px": 50001.0})

    d = r.decide(
        "buy",
        q,
        edge_bps_estimate=3.0,
        latency_ms=10.0,
        fill_features={"obi": 0.5, "spread_bps": 2.0},
    )

    assert d.scores is not None
    assert "p_fill" in d.scores
    assert 0.0 <= d.scores["p_fill"] <= 1.0
    assert d.why_code in [
        "OK_ROUTE_MAKER",
        "OK_ROUTE_TAKER",
        "WHY_UNATTRACTIVE",
        "WHY_SLA_LATENCY",
    ]
