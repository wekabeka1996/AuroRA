from __future__ import annotations

"""
Regime — GLR change detector (Gaussian mean-shift, unknown means)
=================================================================

Mathematical model
------------------
Let x_1..x_n be recent observations in a sliding window of size n (W). Under H0,
all x_i ~ N(μ, σ^2). Under H1, there is a change-point k (1 ≤ k < n) such that
x_1..x_k ~ N(μ1, σ^2), x_{k+1}..x_n ~ N(μ2, σ^2) with μ1 ≠ μ2 (σ^2 known or
estimated). The generalized likelihood ratio statistic (with unknown μ1, μ2) is

    T_n = max_{1 ≤ k < n}  (n1 * n2 / n) * (\bar x_1..k - \bar x_{k+1}..n)^2 / σ^2

where n1=k, n2=n-k, and \bar x are sample means of the two segments.
We trigger a change when T_n ≥ h (threshold).

Properties
----------
- Windowed O(W) update per sample using cumulative sums
- Robust to unknown μ via differenced means
- Optionally estimate σ^2 from the window (pooled variance)

Usage
-----
    glr = GLRMeanShift(window=512, threshold=50.0, sigma2=None)
    for x in stream:
        res = glr.update(x)
        if res.triggered:
            print(res.k_hat, res.stat)
"""

from dataclasses import dataclass


@dataclass
class GLRResult:
    triggered: bool
    stat: float
    k_hat: int | None  # argmax split index within window (1..n-1)
    n: int


class GLRMeanShift:
    def __init__(
        self,
        *,
        window: int = 512,
        threshold: float = 50.0,
        sigma2: float | None = None,
        reset_on_trigger: bool = True,
        min_samples: int = 30,
    ) -> None:
        if window < 2:
            raise ValueError("window must be >= 2")
        self.W = int(window)
        self.h = float(threshold)
        self.sigma2_known = sigma2 if (sigma2 is not None and sigma2 > 0.0) else None
        self.reset_on_trigger = bool(reset_on_trigger)
        self.min_samples = int(min_samples)
        # buffers
        self._x: list[float] = []
        self._n = 0

    def reset(self) -> None:
        self._x.clear()
        self._n = 0

    @property
    def n(self) -> int:
        return self._n

    def _window_sigma2(self) -> float:
        # unbiased sample variance over current window (n-1 in denominator)
        n = len(self._x)
        if n <= 1:
            return 1.0
        mean = sum(self._x) / n
        var = sum((xi - mean) ** 2 for xi in self._x) / max(1, n - 1)
        return max(var, 1e-18)

    def _statistic(self) -> tuple[float, int | None]:
        x = self._x
        n = len(x)
        if n < 2:
            return 0.0, None
        # prefix sums for O(n) scan
        S = [0.0] * (n + 1)
        for i in range(1, n + 1):
            S[i] = S[i - 1] + x[i - 1]
        sigma2 = self.sigma2_known if self.sigma2_known is not None else self._window_sigma2()
        best = 0.0
        k_hat: int | None = None
        for k in range(1, n):
            n1 = k
            n2 = n - k
            m1 = (S[k] - S[0]) / n1
            m2 = (S[n] - S[k]) / n2
            stat = (n1 * n2 / n) * ((m1 - m2) ** 2) / sigma2
            if stat > best:
                best = stat
                k_hat = k
        return best, k_hat

    def update(self, x_new: float) -> GLRResult:
        self._x.append(float(x_new))
        if len(self._x) > self.W:
            # drop oldest
            self._x.pop(0)
        self._n += 1

        # compute statistic over current window
        stat, k_hat = self._statistic()
        triggered = self._n >= self.min_samples and stat >= self.h
        res = GLRResult(triggered=triggered, stat=stat, k_hat=k_hat, n=self._n)
        if triggered and self.reset_on_trigger:
            self.reset()
        return res
