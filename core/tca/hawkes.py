from __future__ import annotations

"""
TCA — Hawkes process (1D, exponential kernel)
=============================================

We model order/trade arrivals by a self-exciting Hawkes process with intensity

    λ(t) = μ + η * ∑_{t_i < t} g_β(t - t_i),  where  g_β(w) = β e^{-β w}

Here η ∈ [0,1) is the branching ratio (expected offspring per event). The kernel
integrates to 1, so total excitation is governed by η.

Implements
---------
- Log-likelihood on [0, T]
- EM estimation of (μ, η, β) after Veen & Schoenberg (2008), exponential kernel
- Ogata's thinning algorithm for simulation

Notes
-----
- Input times must be sorted and within [0, T]; if T is None, T = t_n
- Pure Python; efficient enough for small/medium samples (≤1e5)
"""

from collections.abc import Iterable
from dataclasses import dataclass
import math
import random


@dataclass
class HawkesParams:
    mu: float
    eta: float
    beta: float


# -------------------- core helpers --------------------

def _intensity_at(t: float, times: list[float], params: HawkesParams) -> float:
    mu, eta, beta = params.mu, params.eta, params.beta
    s = 0.0
    # sum over t_i < t of beta * exp(-beta (t - t_i))
    for ti in times:
        if ti >= t:
            break
        s += math.exp(-beta * (t - ti))
    return mu + eta * beta * s


def loglik(times: list[float], params: HawkesParams, T: float | None = None) -> float:
    if not times:
        return -(params.mu * (T if T is not None else 0.0))
    if T is None:
        T = times[-1]
    mu, eta, beta = params.mu, params.eta, params.beta
    # sum log-intensities at event times
    ll = 0.0
    s_tail = 0.0
    s_kernel = 0.0
    for i, ti in enumerate(times):
        # accumulate kernel contribution efficiently
        # s_kernel = sum_{j<i} exp(-beta(ti - t_j))
        s_kernel *= math.exp(-beta * (ti - (times[i - 1] if i > 0 else 0.0)))
        if i > 0:
            s_kernel += 1.0  # from event i-1 at lag 0 after decay applied above
        lam = mu + eta * beta * s_kernel
        ll += math.log(max(lam, 1e-300))

    # integral term:
    # ∫ λ = μ T + η ∑_{j} ∫_{t_j}^T β e^{-β (t - t_j)} dt = μ T + η ∑_{j} (1 - e^{-β (T - t_j)})
    tail = 0.0
    for tj in times:
        tail += 1.0 - math.exp(-beta * (T - tj))
    ll -= mu * T + eta * tail
    return ll


# -------------------- EM estimation --------------------

def fit_em(times: Iterable[float], *, T: float | None = None, max_iter: int = 100, tol: float = 1e-6,
           init: HawkesParams | None = None) -> HawkesParams:
    """Estimate (μ, η, β) by EM for exponential Hawkes.

    References: Veen & Schoenberg (2008)
    """
    t = sorted(float(x) for x in times)
    if not t:
        raise ValueError("no events")
    if T is None:
        T = t[-1]
    if T <= 0:
        raise ValueError("T must be > 0")

    # Initialize
    if init is None:
        mu = max(1e-6, len(t) / (2.0 * T))  # start with half of naive Poisson rate
        eta = 0.3  # modest branching
        beta = 1.0 / max(1e-6, (T / len(t)))  # inverse of mean inter-arrival
    else:
        mu, eta, beta = init.mu, init.eta, init.beta

    for _ in range(max_iter):
        # E-step: responsibilities
        sum_p0 = 0.0
        sum_pij = 0.0
        sum_pij_dt = 0.0

        # For denominator at each ti: μ + η β Σ exp(-β (ti - tj))
        s_kernel = 0.0
        last_t = 0.0
        for i, ti in enumerate(t):
            # decay kernel aggregate to current time
            s_kernel *= math.exp(-beta * (ti - last_t))
            if i > 0:
                s_kernel += 1.0  # contribution of event i-1 at lag 0 after decay
            last_t = ti

            denom = mu + eta * beta * s_kernel
            if denom <= 1e-300:
                denom = 1e-300
            # immigrant prob for event i
            p0 = mu / denom
            sum_p0 += p0

            # offspring responsibilities for pairs (j < i)
            # We accumulate expected #offsp and dt-weighted sum by walking back with decays
            # Using recurrence: exp(-beta (ti - t_{i-1})) etc.
            # Start from event i-1
            w = 1.0
            for j in range(i - 1, -1, -1):
                dt = ti - t[j]
                val = eta * beta * math.exp(-beta * dt) / denom
                sum_pij += val
                sum_pij_dt += val * dt
                # early break if negligible
                if dt * beta > 20.0:
                    break

        # M-step
        mu_new = sum_p0 / T
        # exposure term for eta: sum_j (1 - e^{-β (T - t_j)})
        exposure = 0.0
        for tj in t:
            exposure += 1.0 - math.exp(-beta * (T - tj))
        eta_new = sum_pij / max(exposure, 1e-300)
        # β update: ratio of expected #offspring over expected sum of dt
        beta_new = sum_pij / max(sum_pij_dt, 1e-300)

        # constrain params
        eta_new = min(max(eta_new, 1e-6), 0.999)
        beta_new = max(beta_new, 1e-6)
        mu_new = max(mu_new, 1e-9)

        # check convergence
        if abs(mu_new - mu) + abs(eta_new - eta) + abs(beta_new - beta) < tol:
            mu, eta, beta = mu_new, eta_new, beta_new
            break
        mu, eta, beta = mu_new, eta_new, beta_new

    return HawkesParams(mu=mu, eta=eta, beta=beta)


# -------------------- Simulation (Ogata thinning) --------------------

def simulate(params: HawkesParams, T: float, seed: int | None = None) -> list[float]:
    """Simulate Hawkes events on [0, T] via Ogata's thinning (exponential kernel)."""
    if seed is not None:
        random.seed(seed)
    mu, eta, beta = params.mu, params.eta, params.beta
    t: list[float] = []
    s_kernel: float = 0.0
    current = 0.0
    while current < T:
        # Upper bound for intensity: μ + η β s_kernel (at current)
        lam_bar = mu + eta * beta * s_kernel
        if lam_bar <= 0:
            # no chance of new events; jump to T
            break
        # sample candidate inter-arrival from exponential with rate lam_bar
        u = random.random()
        w = -math.log(max(1e-12, u)) / lam_bar
        current += w
        if current >= T:
            break
        # Update kernel aggregate to new time
        s_kernel *= math.exp(-beta * w)
        # Accept with prob λ(current)/lam_bar
        lam_current = mu + eta * beta * s_kernel
        if random.random() <= lam_current / lam_bar:
            # event occurs
            t.append(current)
            s_kernel += 1.0
    return t


__all__ = ["HawkesParams", "loglik", "fit_em", "simulate"]
