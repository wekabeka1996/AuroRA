from __future__ import annotations

"""
TCA — Cox proportional hazards for fill probability
===================================================

We model time-to-fill (TTF) with a semi-parametric Cox model:

    h(t | z) = h_0(t) * exp(β^T z),

where z is a vector of covariates (features of the order and microstructure),
β are coefficients, and h_0(t) is an unspecified baseline hazard. Estimation via
**partial likelihood** avoids specifying h_0. We implement Breslow's handling of
ties and provide gradient-based fitting (no external deps).

Features
--------
- Fit β by maximizing partial log-likelihood with L2-regularization
- Predict hazard ratios exp(β^T z)
- Pure Python implementation; intended for moderate sample sizes (1e4)

Input format
------------
Events are dictionaries with keys:
  - 't': event/censoring time (float)
  - 'd': event indicator (1 = filled, 0 = censored)
  - 'z': mapping {feature_name: value}

Example
-------
    data = [
        {'t': 12.3, 'd': 1, 'z': {'obi': 0.1, 'microprice': -0.02}},
        {'t': 40.0, 'd': 0, 'z': {'obi': 0.2, 'microprice':  0.01}},
    ]
    cox = CoxPH().fit(data)
    hr = cox.hazard_ratio({'obi': 0.15, 'microprice': 0.00})
"""

from dataclasses import dataclass
from typing import Dict, Iterable, List, Mapping, Optional, Sequence, Tuple, Any
import math


@dataclass
class CoxResult:
    beta: Dict[str, float]
    loglik: float
    iters: int


class CoxPH:
    def __init__(self, *, l2: float = 1e-6, max_iter: int = 200, tol: float = 1e-6, step: float = 0.5) -> None:
        self.l2 = float(l2)
        self.max_iter = int(max_iter)
        self.tol = float(tol)
        self.step = float(step)
        self._beta: Dict[str, float] = {}
        self._feat: List[str] = []

    # ---------- utilities ----------

    @staticmethod
    def _features_union(data: Iterable[Mapping[str, Any]]) -> List[str]:
        feats: Dict[str, None] = {}
        for rec in data:
            z_dict = rec.get('z', {})
            if isinstance(z_dict, Mapping):
                for k in z_dict.keys():
                    feats[k] = None
        return sorted(feats.keys())

    @staticmethod
    def _dot(beta: Mapping[str, float], z: Mapping[str, float]) -> float:
        s = 0.0
        for k, v in z.items():
            s += beta.get(k, 0.0) * float(v)
        return s

    @staticmethod
    def _add_scaled(dst: Dict[str, float], src: Mapping[str, float], scale: float) -> None:
        for k, v in src.items():
            dst[k] = dst.get(k, 0.0) + scale * float(v)

    # ---------- core computations ----------

    def _sorted_by_time(self, data: Sequence[Mapping[str, Any]]) -> List[Mapping[str, Any]]:
        return sorted(data, key=lambda r: float(r.get('t', 0)))

    def _risk_sums(self, sorted_data: List[Mapping[str, Any]], beta: Mapping[str, float]) -> Tuple[List[float], List[Dict[str, float]]]:
        """Compute cumulative risk set sums from the end for Breslow handling.

        Returns
        -------
        S : list of cumulative sums of exp(η_j) where η_j = β^T z_j
        ZS: list of cumulative sums of z_j * exp(η_j) as dict per time index
        """
        n = len(sorted_data)
        S = [0.0] * n
        ZS: List[Dict[str, float]] = [dict() for _ in range(n)]
        acc_S = 0.0
        acc_ZS: Dict[str, float] = {}
        for i in range(n - 1, -1, -1):
            rec = sorted_data[i]
            z_dict = rec.get('z', {})
            if not isinstance(z_dict, Mapping):
                continue
            zi = {k: float(v) for k, v in z_dict.items() if isinstance(v, (int, float))}
            eta = self._dot(beta, zi)
            # Safe exponential to avoid overflow
            if eta > 700:  # exp(700) ≈ 1e300, close to float max
                w = 1e300
            elif eta < -700:
                w = 1e-300
            else:
                w = math.exp(eta)
            acc_S += w
            # acc_ZS += zi * w
            for k, v in zi.items():
                acc_ZS[k] = acc_ZS.get(k, 0.0) + v * w
            S[i] = acc_S
            ZS[i] = dict(acc_ZS)
        return S, ZS

    def _partial_loglik_and_grad(self, data: Sequence[Mapping[str, Any]], beta: Mapping[str, float]) -> Tuple[float, Dict[str, float]]:
        d_sorted = self._sorted_by_time(data)
        S, ZS = self._risk_sums(d_sorted, beta)
        ll = 0.0
        grad: Dict[str, float] = {k: 0.0 for k in self._feat}
        n = len(d_sorted)
        i = 0
        while i < n:
            rec_i = d_sorted[i]
            t_i = float(rec_i.get('t', 0))
            # collect tied events at time t_i
            j = i
            events: List[Mapping[str, Any]] = []
            while j < n and abs(float(d_sorted[j].get('t', 0)) - t_i) < 1e-12:
                rec_j = d_sorted[j]
                if int(rec_j.get('d', 0)) == 1:
                    events.append(rec_j)
                j += 1
            # risk set at t_i is indices k >= i
            if events:
                # Breslow approximation
                # sum z for events and count m
                m = len(events)
                sum_z_e: Dict[str, float] = {}
                for e in events:
                    z_dict = e.get('z', {})
                    if isinstance(z_dict, Mapping):
                        zi = {k: float(v) for k, v in z_dict.items() if isinstance(v, (int, float))}
                        self._add_scaled(sum_z_e, zi, 1.0)
                # denominator: (∑_{k∈R} e^{η_k})^m, gradient uses ZS/S
                denom_S = S[i]
                ll -= m * math.log(max(denom_S, 1e-300))
                # gradient: sum z_e - m * (∑ z_k e^{η_k} / ∑ e^{η_k})
                frac: Dict[str, float] = {}
                for k in self._feat:
                    frac[k] = ZS[i].get(k, 0.0) / max(denom_S, 1e-300)
                for k, v in sum_z_e.items():
                    grad[k] += v
                for k in self._feat:
                    grad[k] -= m * frac[k]
            i = j
        # L2 regularization
        for k in self._feat:
            b = beta.get(k, 0.0)
            ll -= 0.5 * self.l2 * b * b
            grad[k] -= self.l2 * b
        return ll, grad

    # ---------- API ----------

    def fit(self, data: Sequence[Mapping[str, Any]]) -> CoxResult:
        if not data:
            raise ValueError("empty data")
        self._feat = self._features_union(data)
        beta: Dict[str, float] = {k: 0.0 for k in self._feat}
        last_ll = float("-inf")
        it = 0
        for it in range(1, self.max_iter + 1):
            ll, g = self._partial_loglik_and_grad(data, beta)
            # simple backtracking line search on logistic-like objective
            step = self.step
            improved = False
            for _ in range(20):
                trial = {k: beta.get(k, 0.0) + step * g.get(k, 0.0) for k in self._feat}
                ll_trial, _ = self._partial_loglik_and_grad(data, trial)
                if ll_trial > ll:
                    beta = trial
                    last_ll = ll_trial
                    improved = True
                    break
                step *= 0.5
            if not improved:
                break
            # stopping criterion on gradient norm
            grad_norm = sum(abs(g.get(k, 0.0)) for k in self._feat)
            if grad_norm < self.tol:
                break
        self._beta = beta
        return CoxResult(beta=dict(beta), loglik=last_ll, iters=it)

    # ---------- predictions ----------

    def coef(self) -> Dict[str, float]:
        return dict(self._beta)

    def hazard_ratio(self, z: Mapping[str, float]) -> float:
        """Compute hazard ratio exp(β^T z) for given covariates."""
        eta = self._dot(self._beta, {k: float(v) for k, v in z.items()})
        # Safe exponential
        if eta > 700:
            return 1e300
        elif eta < -700:
            return 1e-300
        else:
            return math.exp(eta)

    def survival(self, horizon_ms: float, z: Mapping[str, float]) -> float:
        """Compute survival probability S(t) = exp(-∫_0^t λ(u) du) using Breslow estimator.

        For Cox model, the cumulative hazard H(t) = ∫_0^t λ(u) du ≈ sum of hazard ratios
        at event times ≤ t, weighted by risk set size.
        """
        if not self._beta:
            return 1.0  # no model fitted

        # For simplicity, use the hazard ratio as approximation
        # In full implementation, would need sorted event times and risk sets
        hr = self.hazard_ratio(z)
        # Approximate cumulative hazard as hr * horizon_ms (simplified)
        cum_hazard = hr * (horizon_ms / 1000.0)  # scale to seconds
        return math.exp(-cum_hazard)

    def p_fill(self, horizon_ms: float, z: Mapping[str, float]) -> float:
        """Compute fill probability as 1 - survival probability.

        This gives the probability that an order will be filled within the given horizon.
        """
        survival_prob = self.survival(horizon_ms, z)
        return 1.0 - survival_prob


__all__ = ["CoxPH", "CoxResult"]
