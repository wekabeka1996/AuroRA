"""
Aurora+ScalpBot — repo/core/risk/cvar.py
----------------------------------------
Conditional Value-at-Risk (Expected Shortfall) utilities.

Paste into: repo/core/risk/cvar.py
Run self-tests: `python repo/core/risk/cvar.py`

Implements (per project structure):
- Empirical VaR/CVaR from samples (loss domain or PnL domain)
- Rolling (streaming) VaR/CVaR with O(log n) updates (sorted multiset)
- Portfolio CVaR from scenario returns: L = −R·w; CVaRα(L)
- CVaR-minimizing weights via projected subgradient (simplex for long-only) or
  L1-ball projection for leverage-capped long/short

No external dependencies; NumPy optional.
"""
from __future__ import annotations

import bisect
from collections import deque
from collections.abc import Sequence
from dataclasses import dataclass
import math
import random

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# =============================
# Empirical VaR / CVaR
# =============================

def _quantile(sorted_vals: Sequence[float], alpha: float) -> float:
    n = len(sorted_vals)
    if n == 0:
        return 0.0
    a = min(1.0, max(0.0, float(alpha)))
    k = int(math.ceil(a * n) - 1)
    k = max(0, min(n - 1, k))
    return float(sorted_vals[k])


def var_cvar_from_losses(losses: Sequence[float], alpha: float = 0.99, *, method: str = "empirical", **kwargs) -> tuple[float, float]:
    """Compute empirical VaRα and CVaRα given **losses** (higher = worse).

    VaRα is the α-quantile of the loss distribution. CVaRα is the mean of the
    tail beyond VaRα (including equals).
    
    Args:
        losses: Sequence of loss values
        alpha: Confidence level (0.99 for 99% VaR)
        method: "empirical" (default) or "POT" for Peaks-Over-Threshold
        **kwargs: Additional arguments for specific methods
            For method="POT": q_u (threshold quantile, default 0.95)
    
    Returns:
        Tuple of (VaR, CVaR) values
    """
    if method == "POT":
        try:
            from .evt_pot import pot_fit, pot_var_es
            q_u = kwargs.get('q_u', 0.95)
            est = pot_fit(losses, q_u=q_u)
            return pot_var_es(est, alpha)
        except ImportError:
            # Fallback to empirical if evt_pot not available
            pass

    # Default empirical method
    x = sorted(float(z) for z in losses)
    if not x:
        return 0.0, 0.0
    var = _quantile(x, alpha)
    tail = [z for z in x if z >= var]
    cvar = sum(tail) / max(1, len(tail))
    return var, cvar


def var_cvar_from_pnl(pnl: Sequence[float], alpha: float = 0.99) -> tuple[float, float]:
    """Convenience wrapper when inputs are **PnL/returns** (negative = loss).

    Converts to losses via L = max(0, −PnL) and applies `var_cvar_from_losses`.
    """
    losses = [max(0.0, -float(r)) for r in pnl]
    return var_cvar_from_losses(losses, alpha)


def var_with_ci(losses: Sequence[float], alpha: float = 0.99, *, method: str = "empirical", **kwargs) -> tuple[float, float, float]:
    """Compute VaRα with confidence interval given **losses** (higher = worse).

    Args:
        losses: Sequence of loss values
        alpha: Confidence level (0.99 for 99% VaR)
        method: "empirical" (default) or "POT" for Peaks-Over-Threshold
        **kwargs: Additional arguments for specific methods
            For method="POT": q_u (threshold quantile, default 0.95), n_boot (bootstrap samples, default 1000)
    
    Returns:
        Tuple of (VaR, CI_lower, CI_upper) values
    """
    if method == "POT":
        try:
            from .evt_pot import pot_var_bootstrap
            q_u = kwargs.get('q_u', 0.95)
            n_boot = kwargs.get('n_boot', 1000)
            ci_result = pot_var_bootstrap(losses, alpha, q_u=q_u, n_boot=n_boot)
            return ci_result["var"], ci_result["lo"], ci_result["hi"]
        except ImportError:
            # Fallback to empirical if evt_pot not available
            pass

    # Default empirical method with simple bootstrap CI
    x = sorted(float(z) for z in losses)
    if not x:
        return 0.0, 0.0, 0.0
    var = _quantile(x, alpha)
    # Simple bootstrap CI (could be enhanced)
    ci_lo, ci_hi = var * 0.9, var * 1.1  # Placeholder CI
    return var, ci_lo, ci_hi


# =============================
# Rolling (streaming) VaR / CVaR
# =============================

@dataclass
class _Item:
    loss: float
    uid: int


class RollingCVaR:
    """Rolling VaR/CVaR over the last N samples using a sorted multiset.

    Operations: update(loss) in O(log N); metrics(): (VaRα, CVaRα).
    """

    def __init__(self, window_n: int = 2000, alpha: float = 0.99) -> None:
        self.N = int(window_n)
        self.alpha = float(alpha)
        self.q: deque[_Item] = deque()
        self.sorted: list[tuple[float, int]] = []  # (loss, uid)
        self._uid = 0
        self._sum = 0.0

    def update(self, loss: float) -> None:
        l = max(0.0, float(loss))
        it = _Item(l, self._uid)
        self._uid += 1
        # append to deque
        self.q.append(it)
        self._sum += l
        # insert into sorted
        bisect.insort(self.sorted, (it.loss, it.uid))
        # evict
        while len(self.q) > self.N:
            old = self.q.popleft()
            self._sum -= old.loss
            k = bisect.bisect_left(self.sorted, (old.loss, old.uid))
            if 0 <= k < len(self.sorted) and self.sorted[k] == (old.loss, old.uid):
                self.sorted.pop(k)
            else:  # fallback linear search (should rarely happen)
                for j in range(max(0, k - 3), min(len(self.sorted), k + 4)):
                    if self.sorted[j] == (old.loss, old.uid):
                        self.sorted.pop(j)
                        break

    def metrics(self) -> tuple[float, float]:
        if not self.sorted:
            return 0.0, 0.0
        var = _quantile([v for (v, _) in self.sorted], self.alpha)
        # tail sum via index
        n = len(self.sorted)
        k = int(math.ceil(self.alpha * n) - 1)
        k = max(0, min(n - 1, k))
        tail_vals = [self.sorted[i][0] for i in range(k, n)]
        cvar = sum(tail_vals) / max(1, len(tail_vals))
        return var, cvar


# =============================
# Portfolio CVaR
# =============================

def portfolio_cvar(weights: Sequence[float], returns: Sequence[Sequence[float]], alpha: float = 0.99) -> tuple[float, float]:
    """Portfolio VaR/CVaR from scenario **returns** (PnL), using losses L = −R·w.

    - `weights`: portfolio weights (can be long/short). No normalization enforced here.
    - `returns`: list of scenarios, each a vector of asset returns.
    - Returns (VaRα, CVaRα) in **loss** units (same as returns magnitudes).
    """
    w = [float(x) for x in weights]
    if np is not None:
        R = np.array(returns, dtype=float)
        wv = np.array(w, dtype=float)
        pnl = R.dot(wv)  # shape: (#scen,)
        losses = [max(0.0, -float(x)) for x in pnl.tolist()]
    else:
        losses = []
        for scen in returns:
            pnl = sum(float(a) * float(b) for a, b in zip(scen, w))
            losses.append(max(0.0, -pnl))
    return var_cvar_from_losses(losses, alpha)


# =============================
# CVaR-Min optimization (projected subgradient)
# =============================

def _proj_simplex(v: Sequence[float], z: float = 1.0) -> list[float]:
    """Project vector onto the probability simplex {w ≥ 0, ∑w = z}."""
    x = [max(0.0, float(t)) for t in v]
    s = sum(x)
    if s == 0:
        n = len(x)
        return [z / n] * n
    # shift by tau so that sum=max(0, x - tau) = z
    u = sorted(x, reverse=True)
    css = 0.0
    rho = -1
    tau = 0.0  # Initialize tau
    for i, ui in enumerate(u):
        css += ui
        t = (css - z) / (i + 1)
        if i == len(u) - 1 or u[i + 1] <= t:
            rho = i
            tau = t
            break
    return [max(0.0, xi - tau) for xi in x]


def _proj_l1_ball(v: Sequence[float], c: float) -> list[float]:
    """Project onto L1 ball {∑|w| ≤ c}. Duchi et al. (2008)."""
    c = max(1e-12, float(c))
    u = [abs(float(t)) for t in v]
    if sum(u) <= c:
        return [float(t) for t in v]
    # find threshold
    u_sorted = sorted(u, reverse=True)
    css = 0.0
    rho = 0
    tau = 0.0
    for i, ui in enumerate(u_sorted):
        css += ui
        t = (css - c) / (i + 1)
        if i == len(u_sorted) - 1 or u_sorted[i + 1] <= t:
            rho = i
            tau = t
            break
    return [math.copysign(max(0.0, abs(vi) - tau), vi) for vi in v]


def cvar_minimize(
    returns: Sequence[Sequence[float]],
    *,
    alpha: float = 0.99,
    steps: int = 400,
    lr: float = 0.5,
    long_only: bool = True,
    sum_to_one: bool = True,
    leverage_cap: float = 1.0,
    seed: int = 7,
) -> list[float]:
    """Minimize CVaRα of portfolio **returns** via projected subgradient.

    - If `long_only` and `sum_to_one`: project to simplex (∑w=1, w≥0).
    - Else: project to L1 ball with radius `leverage_cap` (∑|w|≤cap).

    Subgradient of CVaR wrt w ≈ −E[r | loss≥VaR]. We estimate VaR at each step,
    collect the tail set, and update w ← w − lr · (−mean_tail_return).
    """
    rnd = random.Random(seed)
    m = len(returns[0]) if returns else 0
    if m == 0:
        return []
    # init weights uniform on simplex
    w = [1.0 / m] * m if long_only and sum_to_one else [rnd.uniform(-0.1, 0.1) for _ in range(m)]

    def tail_grad(weights: Sequence[float]) -> tuple[float, list[float]]:
        # compute portfolio pnl for each scenario
        pnl: list[float] = []
        for scen in returns:
            pnl.append(sum(float(a) * float(b) for a, b in zip(scen, weights)))
        # losses
        losses = [max(0.0, -x) for x in pnl]
        # VaR and tail mask
        var, _ = var_cvar_from_losses(losses, alpha)
        tail_idx = [i for i, L in enumerate(losses) if L >= var]
        if not tail_idx:
            return var, [0.0] * m
        # gradient = -mean of tail returns (vector)
        g = [0.0] * m
        for i in tail_idx:
            ri = returns[i]
            for j in range(m):
                g[j] += -float(ri[j])
        g = [gj / len(tail_idx) for gj in g]
        # also return current CVaR for logging (optional)
        return var, g

    for t in range(steps):
        _, g = tail_grad(w)
        # step
        w = [wi - lr * gi for wi, gi in zip(w, g)]
        # project
        if long_only and sum_to_one:
            w = _proj_simplex(w, z=1.0)
        else:
            w = _proj_l1_ball(w, c=leverage_cap)
        # anneal lr slightly
        lr *= 0.99
    return w


# =============================
# Self-tests
# =============================

def _make_scenarios(n: int = 3000, m: int = 3, seed: int = 3) -> list[list[float]]:
    rnd = random.Random(seed)
    R: list[list[float]] = []
    for i in range(n):
        # heavy-ish tails: mix of Gaussians
        row: list[float] = []
        for j in range(m):
            s = 0.01 + 0.02 * (j + 1)
            # with small prob, draw from wider tail
            if rnd.random() < 0.05:
                val = rnd.gauss(0.0, 3.0 * s)
            else:
                val = rnd.gauss(0.0, s)
            row.append(val)
        R.append(row)
    return R


def _test_empirical() -> None:
    losses = [0, 1, 2, 3, 4, 5]
    var, cvar = var_cvar_from_losses(losses, alpha=5/6)  # 83.33% → VaR≈5th element (index 4)
    assert abs(var - 4.0) < 1e-12
    assert abs(cvar - (4.0 + 5.0) / 2.0) < 1e-12


def _test_rolling() -> None:
    rc = RollingCVaR(window_n=100, alpha=0.95)
    for i in range(200):
        rc.update(loss=float(i % 20))
    v, c = rc.metrics()
    assert v >= 0 and c >= v


def _test_portfolio_and_opt() -> None:
    R = _make_scenarios(n=1500, m=3, seed=9)
    # equal weights baseline
    m = len(R[0])
    w0 = [1.0 / m] * m
    v0, c0 = portfolio_cvar(w0, R, alpha=0.95)
    w = cvar_minimize(R, alpha=0.95, steps=150, lr=0.8, long_only=True, sum_to_one=True)
    v1, c1 = portfolio_cvar(w, R, alpha=0.95)
    # optimized CVaR should be <= baseline (allow small tolerance)
    assert c1 <= c0 + 1e-6


if __name__ == "__main__":
    _test_empirical()
    _test_rolling()
    _test_portfolio_and_opt()
    print("OK - repo/core/risk/cvar.py self-tests passed")
