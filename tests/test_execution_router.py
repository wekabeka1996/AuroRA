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
    assert dec.route == "maker"
    assert dec.e_maker_bps > 0.0 and dec.e_taker_bps < 0.0


def test_router_sla_denies_taker_fallback_logic():
    # SLA very strict -> taker denied
    r = _router(min_p=0.6, max_latency=5.0, kappa=0.1)
    q = QuoteSnapshot(bid_px=100.00, ask_px=100.04)

    # Case A: maker viable -> choose maker
    decA = r.decide(side="buy", quote=q, edge_bps_estimate=4.0, latency_ms=10.0)
    assert decA.route in ("maker", "deny")
    # With default pfill≈0.6 and half-spread≈1.999, E_maker≈(4+1.999)*0.6>0 ⇒ maker
    assert decA.route == "maker"

    # Case B: maker unattractive: set min_p high to force deny when SLA denies taker
    r_harsh = _router(min_p=0.95, max_latency=5.0, kappa=0.1)
    decB = r_harsh.decide(side="buy", quote=q, edge_bps_estimate=1.0, latency_ms=10.0)
    assert decB.route == "deny"