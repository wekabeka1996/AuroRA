import pytest
from r1.score import get_bridge_score

class B:
    def __init__(self, dEfe, dEmp, dHomeo, p_acf, p_spec, energy, lat):
        self.dEfe = dEfe
        self.dEmp = dEmp
        self.dHomeo = dHomeo
        self.penalty_acf = p_acf
        self.penalty_spec = p_spec
        self.energy = energy
        self.latency = lat

def test_ranking_invariance_to_scalar_weights():
    bridges = [
        B(+0.05, +0.02, +0.01, 0.01, 0.02, 0.1, 0.2),
        B(+0.02, +0.03, +0.02, 0.02, 0.01, 0.2, 0.1),
        B(+0.01, +0.01, +0.03, 0.03, 0.03, 0.3, 0.3),
    ]
    w = {
        'alpha_dEfe': 1.0,
        'beta_dEmp': 0.5,
        'gamma_dHomeo': 0.5,
        'lambda_acf': 0.2,
        'lambda_spec': 0.2,
        'lambda_energy': 0.1,
        'lambda_latency': 0.1,
    }
    s1 = [get_bridge_score(b, w) for b in bridges]
    order1 = sorted(range(len(s1)), key=lambda i: s1[i], reverse=True)
    c = 7.0
    w2 = {k: v * c for k, v in w.items()}
    s2 = [get_bridge_score(b, w2) for b in bridges]
    order2 = sorted(range(len(s2)), key=lambda i: s2[i], reverse=True)
    assert order1 == order2, "Порядок ранжирования должен быть инвариантен к масштабированию весов."
