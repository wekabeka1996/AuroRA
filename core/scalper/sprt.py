from __future__ import annotations

"""
Sequential Probability Ratio Test (SPRT) for fast reconfirmation.

Assumes Normal observations with known sigma and different means mu0 (null) vs mu1 (alt).
The log-likelihood ratio (LLR) increment for an observation x is:

  llr(x) = log N(x|mu1, sigma) - log N(x|mu0, sigma)
         = ((x - mu0)**2 - (x - mu1)**2) / (2 * sigma**2)

We accumulate LLR_t = sum_i llr(x_i) and stop when LLR_t >= A (ACCEPT H1) or
LLR_t <= B (REJECT H1), where typically A ~ log((1-β)/α), B ~ log(β/(1-α)).
"""

from dataclasses import dataclass
from typing import Literal, Sequence


Decision = Literal["CONTINUE", "ACCEPT", "REJECT"]


@dataclass(frozen=True)
class SprtConfig:
    mu0: float
    mu1: float
    sigma: float
    A: float  # upper threshold (accept H1)
    B: float  # lower threshold (reject H1)
    max_obs: int


class SPRT:
    def __init__(self, cfg: SprtConfig) -> None:
        self.cfg = cfg
        self.reset()

    def reset(self) -> None:
        self._llr = 0.0
        self._n = 0

    @staticmethod
    def _llr_inc(x: float, mu0: float, mu1: float, sigma: float) -> float:
        denom = 2.0 * (sigma ** 2)
        return ((x - mu0) ** 2 - (x - mu1) ** 2) / denom

    def update(self, x: float) -> Decision:
        if self._n >= self.cfg.max_obs:
            # Already reached max; provide terminal decision based on sign
            return "ACCEPT" if self._llr >= 0.0 else "REJECT"
        self._llr += self._llr_inc(x, self.cfg.mu0, self.cfg.mu1, self.cfg.sigma)
        self._n += 1
        if self._llr >= self.cfg.A:
            return "ACCEPT"
        if self._llr <= self.cfg.B:
            return "REJECT"
        if self._n >= self.cfg.max_obs:
            return "ACCEPT" if self._llr >= 0.0 else "REJECT"
        return "CONTINUE"

    def run(self, xs: Sequence[float]) -> Decision:
        self.reset()
        decision: Decision = "CONTINUE"
        for x in xs:
            decision = self.update(float(x))
            if decision != "CONTINUE":
                break
        return decision

    # Expose internals for observability
    @property
    def llr(self) -> float:
        return self._llr

    @property
    def n_obs(self) -> int:
        return self._n
