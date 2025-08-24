import types
import numpy as np
import pytest

from trading.main_loop import TradingSystem
from living_latent.execution.gating import DecisionHysteresis, DwellConfig

class DummyAcceptance:
    """Minimal stub to emulate Acceptance.decide returning oscillating states."""
    def __init__(self, seq):
        self.seq = seq
        self.i = 0
    def decide(self, evt):  # returns (decision, info)
        d = self.seq[self.i % len(self.seq)]
        self.i += 1
        # minimal info dict with placeholders
        return d, {'p95_surprisal': 0.0, 'latency_p95': 10.0, 'coverage_ema': 0.95, 'rel_width':0.01}
    def update(self, evt):
        pass

@pytest.fixture
def config_base():
    return {
        'student': {'d_obs': 4, 'd_latent': 2, 'd_hidden': 8, 'checkpoint': None},
        'router': {'num_regimes': 2, 'checkpoint': None},
        'certification': {
            'icp': {'alpha_base': 0.1, 'window': 100, 'eta':0.01},
            'dro': {'alpha':0.95,'lambda_reg':0.1},
            'uncertainty': {'kappa_scale':1.0}
        },
        'trading': {'max_latency_ms': 500.0},
        'governance_profile': None
    }

def _dummy_market_point():
    return {'open':1.0,'high':1.1,'low':0.9,'close':1.05,'volume':1000.0}

def test_hysteresis_reduces_transitions(config_base):
    # Sequence that would alternate every call without hysteresis
    seq = ["PASS","DERISK","PASS","DERISK","PASS","DERISK"]
    # Build system with injected acceptance stub
    ts = TradingSystem(config_base, acceptance=None)
    # Inject acceptance stub & disable internal acceptance usage side-effects
    ts.acceptance = DummyAcceptance(seq)
    # Provide metrics stub
    class MStub:
        def set_decision_churn(self, v):
            self.last_churn = v
        def set_execution_risk_scale(self, v):
            pass
        def count_execution_block(self, reason):
            pass
    ts.metrics = MStub()
    # Provide base_notional & simple risk_gate scale map via existing risk_gate or stub
    if ts.risk_gate is None:
        from living_latent.execution.gating import RiskGate, GatingCfg
        ts.base_notional = 100.0
        ts.risk_gate = RiskGate(GatingCfg(scale_map={'PASS':1.0,'DERISK':0.5,'BLOCK':0.0}, hard_block_on_guard=True, min_notional=0.0, max_notional=1e6))
    # Inject external hysteresis with dwell=2 to suppress every immediate flip
    ts.decision_hysteresis = DecisionHysteresis(DwellConfig(min_dwell_pass=2, min_dwell_derisk=2, min_dwell_block=1))

    decisions = []
    for _ in range(len(seq)):
        out = ts.predict(_dummy_market_point())
        decisions.append(out.get('acceptance_decision'))
    # Count transitions
    trans = sum(decisions[i]!=decisions[i-1] for i in range(1,len(decisions)))
    # Without hysteresis flips would be len(seq)-1; expect fewer now
    assert trans < len(seq)-1, f"Expected reduced transitions, got {trans} vs baseline {len(seq)-1}"
    # Churn metric captured
    assert hasattr(ts.metrics, 'last_churn')

def test_notional_applied_scaling(config_base):
    # Start with PASS then sustained DERISK to allow potential dwell then scaling
    seq = ["PASS"] + ["DERISK"]*5
    ts = TradingSystem(config_base, acceptance=None)
    ts.acceptance = DummyAcceptance(seq)
    if ts.risk_gate is None:
        from living_latent.execution.gating import RiskGate, GatingCfg
        ts.base_notional = 200.0
        ts.risk_gate = RiskGate(GatingCfg(scale_map={'PASS':1.0,'DERISK':0.25,'BLOCK':0.0}, hard_block_on_guard=True, min_notional=0.0, max_notional=1e6))
    ts.decision_hysteresis = DecisionHysteresis(DwellConfig(min_dwell_pass=1, min_dwell_derisk=1, min_dwell_block=1))
    scales = []
    for _ in range(len(seq)):
        out = ts.predict(_dummy_market_point())
        scales.append(out.get('risk_scale'))
    # Expect at least one DERISK scale (0.25) observed
    assert any(abs(s - 0.25) < 1e-6 for s in scales), f"Expected a DERISK risk_scale=0.25 in {scales}"
