import math
from living_latent.execution.gating import RiskGate, GatingCfg


def test_risk_gate_basic_scaling():
    cfg = GatingCfg(scale_map={'PASS':1.0,'DERISK':0.5,'BLOCK':0.0}, hard_block_on_guard=True, min_notional=0.0, max_notional=10.0)
    gate = RiskGate(cfg)
    guards = {'surprisal': False,'latency': False,'coverage': False,'width': False}
    assert gate.scale('PASS', guards, 2.0) == 2.0
    assert math.isclose(gate.scale('DERISK', guards, 2.0), 1.0)
    assert gate.scale('BLOCK', guards, 2.0) == 0.0


def test_risk_gate_hard_block_on_guard():
    cfg = GatingCfg(scale_map={'PASS':1.0,'DERISK':0.5,'BLOCK':0.0}, hard_block_on_guard=True)
    gate = RiskGate(cfg)
    guards = {'surprisal': True,'latency': False,'coverage': False,'width': False}
    assert gate.scale('PASS', guards, 1.0) == 0.0  # guard triggers kill-switch


def test_risk_gate_clipping():
    cfg = GatingCfg(scale_map={'PASS':5.0,'DERISK':0.5,'BLOCK':0.0}, hard_block_on_guard=False, min_notional=1.0, max_notional=3.0)
    gate = RiskGate(cfg)
    guards = {'surprisal': False,'latency': False,'coverage': False,'width': False}
    # PASS would give 5*1=5 -> clip to 3
    assert gate.scale('PASS', guards, 1.0) == 3.0
    # DERISK gives 0.5 -> min clip to 1.0
    assert gate.scale('DERISK', guards, 1.0) == 1.0
