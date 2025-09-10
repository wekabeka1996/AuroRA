from __future__ import annotations

"""
Regime — Page–Hinkley change detector (mean-shift)
===================================================

Mathematical model
------------------
For a streaming series {x_t}, the Page–Hinkley (PH) test detects a persistent
increase/decrease in the mean. Define running mean m_t and cumulative statistic

    PH_t = PH_{t-1} + (x_t - m_{t-1} - δ)

Track extrema M_t = max(PH_1..PH_t) and m_t = min(PH_1..PH_t). A positive
(upward) change is flagged when

    PH_t - m_t > λ_up

and a negative (downward) change when

    M_t - PH_t > λ_down

Parameters δ (tolerance) suppress short-term fluctuations; λ_* are thresholds.

Properties
----------
- One-pass, O(1) memory/time per sample.
- Numerically stable with incremental mean update.
- Two-sided detection with independent λ_up/λ_down.

Usage
-----
    ph = PageHinkley(delta=1e-4, lambda_up=5e-4, lambda_down=5e-4, min_samples=50)
    for x in stream:  # e.g., returns or logits
        res = ph.update(x)
        if res.triggered:
            print(res)

Notes
-----
This implementation exposes both-sided detection, optional reset on trigger,
and returns rich metadata (direction, statistic, extrema, sample index).
"""

from dataclasses import dataclass


@dataclass
class PHResult:
    triggered: bool
    direction: str | None  # 'up' | 'down' | None
    stat: float
    ph: float
    ph_min: float
    ph_max: float
    n: int


class PageHinkley:
    def __init__(
        self,
        *,
        delta: float = 0.0,
        lambda_up: float = 0.0,
        lambda_down: float = 0.0,
        min_samples: int = 30,
        reset_on_trigger: bool = True,
        mean_init: float = 0.0,
    ) -> None:
        self.delta = float(delta)
        self.lambda_up = float(lambda_up)
        self.lambda_down = float(lambda_down)
        self.min_samples = int(min_samples)
        self.reset_on_trigger = bool(reset_on_trigger)

        # state
        self._n = 0
        self._mean = float(mean_init)
        self._ph = 0.0
        self._ph_min = 0.0
        self._ph_max = 0.0

    def reset(self, *, mean_init: float | None = None) -> None:
        self._n = 0
        if mean_init is not None:
            self._mean = float(mean_init)
        self._ph = 0.0
        self._ph_min = 0.0
        self._ph_max = 0.0

    @property
    def n(self) -> int:
        return self._n

    @property
    def mean(self) -> float:
        return self._mean

    @property
    def ph(self) -> float:
        return self._ph

    @property
    def ph_min(self) -> float:
        return self._ph_min

    @property
    def ph_max(self) -> float:
        return self._ph_max

    def update(self, x: float) -> PHResult:
        x = float(x)
        self._n += 1
        # incremental mean (uses previous mean)
        if self._n == 1:
            self._mean = x
        else:
            self._mean += (x - self._mean) / self._n

        # core statistic
        self._ph += x - self._mean - self.delta
        if self._ph < self._ph_min:
            self._ph_min = self._ph
        if self._ph > self._ph_max:
            self._ph_max = self._ph

        # two-sided tests (after warmup)
        trig = False
        direction: str | None = None
        stat = 0.0
        if self._n >= self.min_samples:
            up_stat = self._ph - self._ph_min
            down_stat = self._ph_max - self._ph
            if self.lambda_up > 0.0 and up_stat > self.lambda_up:
                trig, direction, stat = True, "up", up_stat
            elif self.lambda_down > 0.0 and down_stat > self.lambda_down:
                trig, direction, stat = True, "down", down_stat

        res = PHResult(
            triggered=trig,
            direction=direction,
            stat=stat,
            ph=self._ph,
            ph_min=self._ph_min,
            ph_max=self._ph_max,
            n=self._n,
        )

        if trig and self.reset_on_trigger:
            self.reset(mean_init=self._mean)

        return res
