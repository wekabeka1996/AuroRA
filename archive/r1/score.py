from __future__ import annotations
from dataclasses import dataclass
from typing import Mapping

@dataclass
class BridgeFeatures:
    dEfe: float
    dEmp: float
    dHomeo: float
    penalty_acf: float
    penalty_spec: float
    energy: float
    latency: float


def get_bridge_score(b, w: Mapping[str, float]) -> float:
    """Скор мостика по весам (линейная агрегирующая формула).

    Положительные компоненты: dEfe, dEmp, dHomeo (улучшения).
    Негативные (штрафы): penalty_acf, penalty_spec, energy, latency.

    Формула: S = α*dEfe + β*dEmp + γ*dHomeo - λ_acf*penalty_acf - λ_spec*penalty_spec
                  - λ_energy*energy - λ_latency*latency

    Масштабирование всех весов на константу не меняет порядок.
    """
    return (
        w.get('alpha_dEfe', 1.0) * b.dEfe +
        w.get('beta_dEmp', 0.5) * b.dEmp +
        w.get('gamma_dHomeo', 0.5) * b.dHomeo -
        w.get('lambda_acf', 0.2) * b.penalty_acf -
        w.get('lambda_spec', 0.2) * b.penalty_spec -
        w.get('lambda_energy', 0.1) * b.energy -
        w.get('lambda_latency', 0.1) * b.latency
    )

__all__ = ["BridgeFeatures", "get_bridge_score"]
