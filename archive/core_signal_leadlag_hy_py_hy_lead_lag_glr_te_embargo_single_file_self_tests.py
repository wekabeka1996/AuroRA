"""
Aurora+ScalpBot — core/signal/leadlag_hy.py
-------------------------------------------
Lead–lag analytics on asynchronous streams using Hayashi–Yoshida (HY),
with Gaussian GLR statistic, simple Transfer Entropy (TE) proxy, and
embargo control to avoid look-ahead in live evaluation.

Paste into: repo/core/signal/leadlag_hy.py
Run self-tests: `python repo/core/signal/leadlag_hy.py`

Implements (per Road_map structure):
- HY covariance/correlation & rolling betas for (X, Y)
- Lead–lag scan over lag grid → τ* (best lag by |corr|)
- GLR (Gaussian) test stat for H0: ρ = 0 vs H1: ρ = ρ̂(τ)
- TE proxy (discrete, 2-bin signs) for directionality X→Y and Y→X at τ*
- Embargo: ignore last Δ seconds within window to prevent leakage in online eval

No external dependencies; NumPy optional.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Deque, Dict, List, Optional, Sequence, Tuple
import math
import random
import time

try:
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover
    np = None  # type: ignore

# --------------------------- Data structures ---------------------------

@dataclass
class _Point:
    t: float
    logp: float


class LeadLagHY:
    """Buffers ticks per symbol and provides on-demand HY/lead–lag analytics."""

    def __init__(self, window_s: float = 60.0, max_points: int = 12000) -> None:
        self.window_s = float(window_s)
        self.max_points = int(max_points)
        self._buf: Dict[str, Deque[_Point]] = {}

    # --------------------------- Ingestion ---------------------------
    def add_tick(self, symbol: str, ts: float, price: float) -> None:
        if price <= 0:
            return
        dq = self._buf.setdefault(symbol, deque())
        dq.append(_Point(float(ts), math.log(float(price))))
        # evict oldest by count
        while len(dq) > self.max_points:
            dq.popleft()
        # evict by time using current ts
        self._evict_old(symbol, ts)

    def _evict_old(self, symbol: str, now_ts: float) -> None:
        dq = self._buf.get(symbol)
        if not dq:
            return
        cutoff = float(now_ts) - self.window_s
        while dq and dq[0].t < cutoff:
            dq.popleft()

    # ------------------------ HY core helpers ------------------------
    @staticmethod
    def _returns(points: Sequence[_Point]) -> List[Tuple[float, float, float]]:
        """Return intervals (t_{i-1}, t_i] with log-returns.
        Output: list of (t0, t1, r).
        """
        out: List[Tuple[float, float, float]] = []
        if len(points) < 2:
            return out
        t0 = points[0].t
        p0 = points[0].logp
        for i in range(1, len(points)):
            t1 = points[i].t
            p1 = points[i].logp
            if t1 > t0:
                out.append((t0, t1, p1 - p0))
            t0, p0 = t1, p1
        return out

    @staticmethod
    def _hy_cov(rx: Sequence[Tuple[float, float, float]], ry: Sequence[Tuple[float, float, float]]) -> Tuple[float, float, float, int]:
        cov = 0.0
        varx = 0.0
        vary = 0.0
        for _, _, r in rx:
            varx += r * r
        for _, _, s in ry:
            vary += s * s
        i = 0
        j = 0
        n_eff = 0
        while i < len(rx) and j < len(ry):
            a0, a1, ri = rx[i]
            b0, b1, sj = ry[j]
            if min(a1, b1) > max(a0, b0):
                cov += ri * sj
                n_eff += 1
            if a1 <= b1:
                i += 1
            else:
                j += 1
        return cov, varx, vary, max(1, n_eff)

    def _prepare_r(self, sym: str, now_ts: Optional[float], embargo_s: float) -> List[Tuple[float, float, float]]:
        dq = self._buf.get(sym, deque())
        if not dq:
            return []
        if now_ts is None:
            now_ts = dq[-1].t
        self._evict_old(sym, now_ts)
        # ignore last embargo_s seconds to avoid leakage
        t_max = float(now_ts) - max(0.0, embargo_s)
        cutoff = t_max - self.window_s
        pts = [pt for pt in dq if cutoff <= pt.t <= t_max]
        return self._returns(pts)

    @staticmethod
    def _shift_r(r: Sequence[Tuple[float, float, float]], lag: float) -> List[Tuple[float, float, float]]:
        if abs(lag) < 1e-15:
            return list(r)
        return [(a + lag, b + lag, v) for (a, b, v) in r]

    # ----------------------------- API -----------------------------
    def hy_metrics(
        self,
        x: str,
        y: str,
        *,
        now_ts: Optional[float] = None,
        lag_s: float = 0.0,
        embargo_s: float = 0.0,
    ) -> Dict[str, float]:
        rx = self._prepare_r(x, now_ts, embargo_s)
        ry0 = self._prepare_r(y, now_ts, embargo_s)
        ry = self._shift_r(ry0, lag_s)
        cov, varx, vary, n_eff = self._hy_cov(rx, ry)
        corr = 0.0 if varx <= 0 or vary <= 0 else cov / math.sqrt(varx * vary)
        beta_x_on_y = 0.0 if vary <= 0 else cov / vary
        beta_y_on_x = 0.0 if varx <= 0 else cov / varx
        # Gaussian GLR for H0: rho=0 vs H1: rho=rho_hat
        # LL ~ -n/2 * log(1 - r^2); GLR = 2(LL(r_hat) - LL(0)) = n * log(1/(1-r^2))
        r2 = min(0.999999, max(0.0, corr * corr))
        glr = float(n_eff) * math.log(1.0 / max(1e-12, (1.0 - r2))) if r2 > 0 else 0.0
        return {
            "hy_cov": cov,
            "hy_corr": corr,
            "var_x": varx,
            "var_y": vary,
            "beta_x_on_y": beta_x_on_y,
            "beta_y_on_x": beta_y_on_x,
            "n_eff": float(n_eff),
            "glr_stat": glr,
        }

    def lead_lag_scan(
        self,
        x: str,
        y: str,
        *,
        lags: Sequence[float] = (-2.0, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5, 1.0, 2.0),
        now_ts: Optional[float] = None,
        embargo_s: float = 0.0,
    ) -> Dict[str, object]:
        best_lag = 0.0
        best_corr = 0.0
        corr_by_lag: Dict[float, float] = {}
        glr_by_lag: Dict[float, float] = {}
        for tau in lags:
            m = self.hy_metrics(x, y, now_ts=now_ts, lag_s=float(tau), embargo_s=embargo_s)
            corr_by_lag[float(tau)] = m["hy_corr"]
            glr_by_lag[float(tau)] = m["glr_stat"]
            if abs(m["hy_corr"]) > abs(best_corr):
                best_corr = m["hy_corr"]
                best_lag = float(tau)
        base = self.hy_metrics(x, y, now_ts=now_ts, lag_s=0.0, embargo_s=embargo_s)
        return {
            "hy_corr_0": base["hy_corr"],
            "hy_cov_0": base["hy_cov"],
            "beta_x_on_y_0": base["beta_x_on_y"],
            "beta_y_on_x_0": base["beta_y_on_x"],
            "corr_by_lag": corr_by_lag,
            "glr_by_lag": glr_by_lag,
            "best_lag": best_lag,
            "best_corr": best_corr,
        }

    # ----------------------------- TE proxy -----------------------------
    @staticmethod
    def _sign_bin(x: float, eps: float = 1e-12) -> int:
        if x > eps:
            return 1
        if x < -eps:
            return -1
        return 0

    def transfer_entropy(
        self,
        x: str,
        y: str,
        *,
        lag_s: float,
        now_ts: Optional[float] = None,
        embargo_s: float = 0.0,
        grid_points: int = 300,
        eps: float = 1e-12,
    ) -> Tuple[float, float]:
        """Return (TE_{X→Y}, TE_{Y→X}) at specified lag using 2-bin sign proxy.

        Procedure:
        - Build stepwise log-price paths from buffered ticks (last window − embargo).
        - Sample both on a uniform grid of `grid_points` within the horizon.
        - Compute discrete returns (first difference), bin to {−1, +1} ignoring zeros.
        - Estimate TE with add-α smoothing (α=0.5) from counts over triples.
        """
        rx = self._prepare_r(x, now_ts, embargo_s)
        ry0 = self._prepare_r(y, now_ts, embargo_s)
        ry = self._shift_r(ry0, lag_s)
        # derive step paths
        def build_path(r: Sequence[Tuple[float, float, float]]) -> Tuple[List[float], List[float]]:
            ts: List[float] = []
            lp: List[float] = []
            if not r:
                return ts, lp
            ts.append(r[0][0])
            s = 0.0
            lp.append(s)
            for (a, b, v) in r:
                ts.append(b)
                s = s + v
                lp.append(s)
            return ts, lp
        tx, px = build_path(rx)
        ty, py = build_path(ry)
        if not tx or not ty:
            return 0.0, 0.0
        t0 = max(tx[0], ty[0])
        t1 = min(tx[-1], ty[-1])
        if t1 <= t0:
            return 0.0, 0.0
        # uniform grid
        gp = max(10, int(grid_points))
        grid = [t0 + (t1 - t0) * i / gp for i in range(gp + 1)]
        def sample(ts: List[float], vs: List[float], t: float) -> float:
            # right-constant step function
            lo, hi = 0, len(ts) - 1
            if t <= ts[0]:
                return vs[0]
            if t >= ts[-1]:
                return vs[-1]
            while lo <= hi:
                mid = (lo + hi) // 2
                if ts[mid] <= t:
                    lo = mid + 1
                else:
                    hi = mid - 1
            return vs[hi]
        xg = [sample(tx, px, t) for t in grid]
        yg = [sample(ty, py, t) for t in grid]
        # discrete diffs
        dx = [xg[i] - xg[i - 1] for i in range(1, len(xg))]
        dy = [yg[i] - yg[i - 1] for i in range(1, len(yg))]
        # binarize to {-1, +1}; ignore zeros by mapping to previous sign
        def to_signs(d: List[float]) -> List[int]:
            out: List[int] = []
            prev = 0
            for v in d:
                s = self._sign_bin(v, eps)
                if s == 0:
                    s = prev if prev != 0 else 1
                out.append(s)
                prev = s
            return out
        sx = to_signs(dx)
        sy = to_signs(dy)
        # TE(X→Y) using counts of (Y_t, Y_{t-1}, X_{t-1})
        def te_xy(src: List[int], dst: List[int]) -> float:
            alpha = 0.5
            # state space {-1, +1} → index {0,1}
            def idx(v: int) -> int:
                return 0 if v < 0 else 1
            c_xyz = [[[alpha for _ in range(2)] for _ in range(2)] for _ in range(2)]
            c_yz = [[alpha for _ in range(2)] for _ in range(2)]
            c_xz = [[alpha for _ in range(2)] for _ in range(2)]
            c_z = [alpha for _ in range(2)]
            for t in range(1, len(dst)):
                y_t = idx(dst[t])
                y_p = idx(dst[t - 1])
                x_p = idx(src[t - 1])
                c_xyz[y_t][y_p][x_p] += 1.0
                c_yz[y_t][y_p] += 1.0
                c_xz[x_p][y_p] += 1.0
                c_z[y_p] += 1.0
            te = 0.0
            for y_t in range(2):
                for y_p in range(2):
                    for x_p in range(2):
                        p_xyz = c_xyz[y_t][y_p][x_p]
                        p_yz = c_yz[y_t][y_p]
                        p_xz = c_xz[x_p][y_p]
                        p_z = c_z[y_p]
                        te += p_xyz * (math.log(p_xyz * p_z + 1e-12) - math.log(p_yz * p_xz + 1e-12))
            # normalize by total count to approximate bits (natural logs → nats)
            total = sum(c_z)
            return max(0.0, te / max(1e-12, total))
        te_xy_val = te_xy(sx, sy)
        te_yx_val = te_xy(sy, sx)
        return float(te_xy_val), float(te_yx_val)


# =============================
# Self-tests (synthetic)
# =============================

def _simulate_pair(T: float = 40.0, seed: int = 7) -> Tuple[List[Tuple[float, float]], List[Tuple[float, float]]]:
    """Irregular pair with Y leading X by L seconds."""
    random.seed(seed)
    dt = 0.01
    n = int(T / dt)
    L = 0.5
    sigma = 0.02
    eps = 0.0005
    ts_dense = [i * dt for i in range(n + 1)]
    S = [0.0]
    s = 0.0
    for i in range(1, n + 1):
        s += sigma * random.gauss(0.0, math.sqrt(dt))
        S.append(s)
    def sample_latent(t: float) -> float:
        if t <= 0: return S[0]
        if t >= T: return S[-1]
        k = int(t / dt)
        t0, t1 = k * dt, (k + 1) * dt
        w = 0.0 if t1 == t0 else (t - t0) / (t1 - t0)
        return (1 - w) * S[k] + w * S[k + 1]
    lam_x, lam_y = 12.0, 11.0
    X: List[Tuple[float, float]] = []
    t = 0.0
    while t < T:
        t += random.expovariate(lam_x)
        if t > T: break
        X.append((t, math.exp(sample_latent(t) + random.gauss(0, eps))))
    Y: List[Tuple[float, float]] = []
    t = 0.0
    while t < T:
        t += random.expovariate(lam_y)
        if t > T: break
        Y.append((t, math.exp(sample_latent(min(T, t + L)) + random.gauss(0, eps))))
    return X, Y


def _test_end_to_end() -> None:
    X, Y = _simulate_pair(T=35.0, seed=13)
    ll = LeadLagHY(window_s=25.0, max_points=20000)
    for (t, p) in X:
        ll.add_tick("X", t, p)
    for (t, p) in Y:
        ll.add_tick("Y", t, p)
    scan = ll.lead_lag_scan("X", "Y", lags=[-2.0, -1.0, -0.75, -0.5, -0.25, 0.0, 0.25, 0.5], embargo_s=0.2)
    assert -0.8 <= scan["best_lag"] <= -0.2
    m0 = ll.hy_metrics("X", "Y", lag_s=0.0, embargo_s=0.2)
    m_star = ll.hy_metrics("X", "Y", lag_s=scan["best_lag"], embargo_s=0.2)
    assert abs(m_star["hy_corr"]) >= abs(m0["hy_corr"]) - 1e-6
    # GLR at τ* should be positive and typically larger than at zero
    assert m_star["glr_stat"] >= m0["glr_stat"] - 1e-9
    # TE: since Y leads X, TE(Y→X) should be >= TE(X→Y) in most cases
    te_xy, te_yx = ll.transfer_entropy("X", "Y", lag_s=scan["best_lag"], embargo_s=0.2)
    assert te_yx >= te_xy - 1e-6


if __name__ == "__main__":
    _test_end_to_end()
    print("OK - core/signal/leadlag_hy.py self-tests passed")
