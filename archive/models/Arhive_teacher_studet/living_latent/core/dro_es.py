from __future__ import annotations
import numpy as np

# Lightweight objective wrapper for DRO-ES monotonicity testing.
# We emulate a conservative ES objective that increases with eps:
# base_es = empirical ES_alpha of losses; objective = base_es + eps * penalty
# For demonstration, penalty = L2 norm of centered losses scaled.

def empirical_es(losses: np.ndarray, es_alpha: float) -> float:
    if losses.size == 0:
        return float('nan')
    # Expected Shortfall (right tail) for losses (assume losses >= 0 means worse)
    q = np.quantile(losses, es_alpha)
    tail = losses[losses >= q]
    if tail.size == 0:
        return float(q)
    return float(tail.mean())

def dro_es_objective(losses: np.ndarray, es_alpha: float = 0.975, eps: float = 0.0) -> float:
    losses = np.asarray(losses, dtype=float)
    base = empirical_es(losses, es_alpha)
    # penalty term approximates robustification cost
    centered = losses - losses.mean()
    penalty = np.sqrt(np.mean(centered**2))  # std
    return base + eps * penalty

__all__ = ["dro_es_objective"]
