from __future__ import annotations
import math
from dataclasses import dataclass
from collections import deque
from typing import Deque, List
import numpy as np

EPS = 1e-9

__all__ = ["P2Quantile", "AdaptiveICP"]

class P2Quantile:
    """Approximate streaming quantile estimator (P^2 algorithm).
    Maintains 5 markers to estimate a target quantile (default high tail 1-alpha).
    Reference: Jain & Chlamtac (1985), P2 algorithm for dynamic quantile estimation.
    """
    def __init__(self, p: float):
        if not (0 < p < 1):
            raise ValueError("p must be in (0,1)")
        self.p = p
        self.n = 0
        self.initial: List[float] = []
        self.q: List[float] = [0.0]*5
        # desired (float) and actual (int) marker positions
        self.np: List[float] = [0.0,0.0,0.0,0.0,0.0]
        self.ni: List[int] = [0,0,0,0,0]
        # increments for desired positions each observation
        self.dn: List[float] = [0.0, self.p/2, self.p, (1+self.p)/2, 1.0]

    def update(self, x: float):
        if not math.isfinite(x):
            return
        if self.n < 5:
            self.initial.append(x)
            self.n += 1
            if self.n == 5:
                self.initial.sort()
                self.q = self.initial[:]  # marker heights
                self.ni = [0,1,2,3,4]
                self.np = [0.0, 2*self.p, 4*self.p, 2+2*self.p, 4.0]
            return
        # find cell k
        k = 0
        if x < self.q[0]:
            self.q[0] = x
            k = 0
        elif x >= self.q[4]:
            self.q[4] = x
            k = 3
        else:
            for i in range(1,5):
                if x < self.q[i]:
                    k = i-1
                    break
        for i in range(k+1,5):
            self.ni[i] += 1
        for i in range(5):
            self.np[i] = float(self.np[i] + self.dn[i])
        # adjust heights
        for i in range(1,4):
            d = self.np[i] - self.ni[i]
            if (d >= 1 and self.ni[i+1]-self.ni[i] > 1) or (d <= -1 and self.ni[i]-self.ni[i-1] > 1):
                dsign = 1 if d > 0 else -1
                qn = self._parabolic(i, dsign)
                if self.q[i-1] < qn < self.q[i+1]:
                    self.q[i] = qn
                else:  # linear
                    self.q[i] = self._linear(i, dsign)
                self.ni[i] += dsign
        self.n += 1

    def value(self) -> float:
        if self.n < 5:
            if self.n == 0:
                return float('nan')
            arr = sorted(self.initial)
            k = int((len(arr)-1)*self.p)
            return arr[k]
        return float(self.q[2])

    # --- Persistence API (Batch-009) ---
    def get_state(self) -> dict:
        return {
            'p': self.p,
            'n': self.n,
            'initial': list(self.initial),
            'q': list(self.q),
            'np': list(self.np),
            'ni': list(self.ni),
            'dn': list(self.dn),
        }

    def set_state(self, s: dict):
        try:
            self.p = s.get('p', self.p)
            self.n = s.get('n', self.n)
            self.initial = list(s.get('initial', []))
            self.q = list(s.get('q', self.q))
            self.np = list(s.get('np', self.np))
            self.ni = list(s.get('ni', self.ni))
            # dn derived from p typically, but keep if provided
            self.dn = list(s.get('dn', self.dn))
        except Exception:
            pass

    def _parabolic(self, i: int, d: int) -> float:
        return self.q[i] + d/(self.ni[i+1]-self.ni[i-1]) * ((self.ni[i]-self.ni[i-1]+d)*(self.q[i+1]-self.q[i])/(self.ni[i+1]-self.ni[i]) + (self.ni[i+1]-self.ni[i]-d)*(self.q[i]-self.q[i-1])/(self.ni[i]-self.ni[i-1]))

    def _linear(self, i: int, d: int) -> float:
        return self.q[i] + d*(self.q[i+d]-self.q[i])/(self.ni[i+d]-self.ni[i])

@dataclass
class ICPStats:
    alpha: float
    coverage_ema: float
    miss_rate_window: float
    q_estimate: float
    count: int

class AdaptiveICP:
    def __init__(self, alpha_target: float = 0.1, eta: float = 0.01, window: int = 1000, quantile_mode: str = "p2",
                 # AUR-ALPHA-710 dynamic alpha modulation params (optional)
                 alpha_min: float | None = None, alpha_max: float | None = None,
                 aci_beta: float | None = None, aci_up_thresh: float | None = None,
                 alpha_k_up: float | None = None, cooldown_steps: int | None = None,
                 decay_tau: int | None = None):
        """Adaptive ICP with optional P² quantile estimation.

        Spec tweaks (BATCH-002):
        - eta base = 0.01, while in transition cooldown use 0.03
        - cooldown length = 25 steps after a detected transition
        - inflation factor: 1 + min(0.25, 0.5*max(0, s/s_thr - 1)), s_thr=2.5
        - coverage EMA beta=0.005 (slow ~400-500 window)
        - P² estimator deferred until >=100 scores else fallback to deque quantile
        """
        # Core targets & parameters
        self.alpha_target = alpha_target
        self.alpha = alpha_target
        self.eta_base = eta
        self.eta_transition = 0.03
        self.window = window
        self.quantile_mode = quantile_mode

        # Buffers
        self.scores: Deque[float] = deque(maxlen=window)
        self.misses: Deque[int] = deque(maxlen=window)

        # Coverage tracking & transition control
        self.coverage_ema = 1 - alpha_target
        self.ema_beta = 0.005
        self._transition_cooldown = 0
        self._cooldown_len = 25
        self._inflation_factor = 1.0
        self._s_thr = 2.5
        self._p2 = P2Quantile(1 - self.alpha) if quantile_mode == 'p2' else None

        # --- Dynamic alpha modulation state (AUR-ALPHA-710) ---
        self.alpha_base = self.alpha_target
        self.alpha_min = alpha_min if alpha_min is not None else max(0.01, 0.6 * self.alpha_base)
        self.alpha_max = alpha_max if alpha_max is not None else min(0.5, 2.0 * self.alpha_base)
        self.aci_beta = aci_beta if aci_beta is not None else 0.2
        self.aci_up_thresh = aci_up_thresh if aci_up_thresh is not None else 1.25
        self.alpha_k_up = alpha_k_up if alpha_k_up is not None else 0.5
        self.cooldown_steps = cooldown_steps if cooldown_steps is not None else 500
        self.decay_tau = decay_tau if decay_tau is not None else 300
        self._aci_ema = 1.0
        self._alpha_eff = self.alpha
        self._cooldown_dyn = 0

    def _effective_sigma(self, sigma: float, mu: float) -> float:
        return max(sigma, 1e-6 * max(1.0, abs(mu)))

    def _detect_transition(self, s: float) -> bool:
        # Heuristic: large standardized score spike triggers a short cooldown inflation
        if len(self.scores) < 30:
            return False
        recent = float(np.mean(list(self.scores)[-30:]))
        if s > 3.0 * max(1e-6, recent):
            return True
        return False

    def predict(self, mu: float, sigma: float) -> tuple[float, float]:
        sigma_eff = self._effective_sigma(sigma, mu)
        # choose q
        if self._p2 is not None and len(self.scores) >= 100:
            q = self._p2.value()
            if not math.isfinite(q) or q <= 0:
                q = float(np.quantile(self.scores, 1 - self.alpha)) if self.scores else abs(np.quantile(np.random.standard_normal(5000), 1 - self.alpha/2))
        else:
            if len(self.scores) < 50:
                q = abs(np.quantile(np.random.standard_normal(5000), 1 - self.alpha/2))
            else:
                q = float(np.quantile(self.scores, 1 - self.alpha))
        q *= self._inflation_factor
        margin = q * sigma_eff
        return float(mu - margin), float(mu + margin)

    def update(self, y: float, mu: float, sigma: float):
        """Update ICP with an observed point.

        Steps:
        1. Compute standardized residual |y-mu|/sigma_eff
        2. Record miss indicator vs current interval
        3. Adapt alpha toward target (fast/slow depending on transition)
        4. Apply dynamic alpha modulation (ACI-based) layering
        5. Update coverage EMA & transition inflation mechanics
        6. Periodically refresh P² estimator with new alpha
        """
        sigma_eff = self._effective_sigma(sigma, mu)
        s = abs(y - mu) / (sigma_eff + EPS)
        self.scores.append(s)
        lo, hi = self.predict(mu, sigma)
        miss = int(not (lo <= y <= hi))
        self.misses.append(miss)

        # 3. Base adaptive alpha step
        eta = self.eta_transition if self._transition_cooldown > 0 else self.eta_base
        self.alpha = float(np.clip(self.alpha - eta * (miss - self.alpha_target), 0.01, 0.5))

        # 4. Dynamic modulation (uses standardized score as provisional ACI proxy if none supplied externally)
        self._modulate_alpha(aci_value=s)

        # 5. Coverage EMA & transition inflation
        self.coverage_ema = (1 - self.ema_beta) * self.coverage_ema + self.ema_beta * (1 - miss)
        if self._detect_transition(s):
            infl = 1.0 + min(0.25, 0.5 * max(0.0, s / self._s_thr - 1.0))
            self._inflation_factor = max(self._inflation_factor, infl)
            self._transition_cooldown = self._cooldown_len
        if self._transition_cooldown > 0:
            self._transition_cooldown -= 1
            if self._transition_cooldown == 0:
                self._inflation_factor = 1.0

        # 6. Refresh P² estimator periodically to reflect updated alpha (only when enough data)
        if self._p2 is not None and len(self.scores) >= 100 and len(self.scores) % 40 == 0:
            new_p2 = P2Quantile(1 - self.alpha)
            for v in self.scores:
                new_p2.update(v)
            self._p2 = new_p2

    def stats(self) -> ICPStats:
        if len(self.misses) > 0:
            miss_rate_window = 1 - (sum(self.misses)/len(self.misses))
        else:
            miss_rate_window = float('nan')
        q_est = self._p2.value() if self._p2 is not None else (float(np.quantile(self.scores, 1 - self.alpha)) if self.scores else float('nan'))
        return ICPStats(alpha=self.alpha, coverage_ema=self.coverage_ema, miss_rate_window=miss_rate_window, q_estimate=q_est, count=len(self.scores))

    # --- ACI dynamic alpha API (AUR-ALPHA-710) ---
    def update_aci(self, aci_value: float) -> float:
        self._aci_ema = (1 - self.aci_beta) * self._aci_ema + self.aci_beta * float(aci_value)
        return self._aci_ema

    def _modulate_alpha(self, aci_value: float | None = None):
        if aci_value is not None:
            self.update_aci(aci_value)
        # Raise alpha if instability (aci_ema > threshold)
        if self._aci_ema > self.aci_up_thresh:
            bump = self.alpha_k_up * (self._aci_ema - self.aci_up_thresh)
            self._alpha_eff = min(self.alpha_max, self.alpha_base * (1.0 + bump))
            self._cooldown_dyn = self.cooldown_steps
        else:
            if self._cooldown_dyn > 0:
                self._cooldown_dyn -= 1
            else:
                # exponential-style relaxation toward base
                d = (self.alpha_base - self._alpha_eff)
                self._alpha_eff += d * (1.0 / max(1, self.decay_tau))
        # Clamp
        self._alpha_eff = float(np.clip(self._alpha_eff, self.alpha_min, self.alpha_max))
        # Expose effective alpha to public field (used by intervals)
        # For now blend original alpha and effective by taking max (more conservative widening when effective> current)
        if self._alpha_eff > self.alpha:
            self.alpha = float(np.clip(self._alpha_eff, self.alpha_min, self.alpha_max))

    def effective_alpha(self) -> float:
        return float(self._alpha_eff)

    def aci_ema(self) -> float:
        return float(self._aci_ema)
