from __future__ import annotations

"""
Governance — Sequential GLR/SPRT with Alpha-Ledger
==================================================

Implements a general-purpose Sequential Probability Ratio Test (SPRT) with
per-sample log-likelihood ratio (LLR) updates and Wald thresholds derived from
(α, β). Includes convenience LLRs for Gaussian (known σ²) and Bernoulli.
Optionally integrates with `AlphaLedger` to account for α-budget spending.

Mathematics
----------
For desired type-I error α and type-II error β, the Wald boundaries for the
cumulative LLR S_n = \sum_i log(f1(x_i)/f0(x_i)) are

    A = log((1 - β) / α),   B = log(β / (1 - α)).

Decision rules
--------------
- If S_n ≥ A → accept H1 (reject H0)
- If S_n ≤ B → accept H0
- Else → continue sampling

API
---
    sprt = SPRT(alpha=0.05, beta=0.1)
    sprt.start(ledger=L, test_name="daily sprt")
    for x in stream:
        r = sprt.update_llr(gaussian_llr(x, mu0=0.0, mu1=0.5, sigma2=1.0))
        if r.final:
            break

"""

from dataclasses import dataclass
from math import log
from typing import Optional

from core.governance.alpha_ledger import AlphaLedger


@dataclass
class SPRTResult:
    final: bool
    decision: str  # 'continue'|'accept_H1'|'accept_H0'
    S: float
    A: float
    B: float
    n: int


def gaussian_llr(x: float, *, mu0: float, mu1: float, sigma2: float) -> float:
    """Per-sample LLR for N(mu1, σ²) vs N(mu0, σ²) with known variance σ².

    LLR(x) = ((mu1 - mu0)/σ²) * (x - (mu1 + mu0)/2).
    """
    return ((mu1 - mu0) / float(sigma2)) * (float(x) - 0.5 * (mu1 + mu0))


def bernoulli_llr(x: int, *, p0: float, p1: float) -> float:
    from math import log
    x = 1 if int(x) == 1 else 0
    p0 = max(1e-12, min(1 - 1e-12, float(p0)))
    p1 = max(1e-12, min(1 - 1e-12, float(p1)))
    return x * log(p1 / p0) + (1 - x) * log((1 - p1) / (1 - p0))


class SPRT:
    def __init__(self, *, alpha: float = 0.05, beta: float = 0.1, reset_on_decision: bool = True) -> None:
        if not (0.0 < alpha < 1.0 and 0.0 < beta < 1.0):
            raise ValueError("alpha, beta must be in (0,1)")
        self.alpha = float(alpha)
        self.beta = float(beta)
        self.A = log((1.0 - self.beta) / self.alpha)
        self.B = log(self.beta / (1.0 - self.alpha))
        self.reset_on_decision = bool(reset_on_decision)
        self._S = 0.0
        self._n = 0
        self._ledger: Optional[AlphaLedger] = None
        self._ticket: Optional[str] = None
        self._test_name: str = ""

    def start(self, *, ledger: Optional[AlphaLedger] = None, test_name: str = "") -> None:
        self._S = 0.0
        self._n = 0
        self._ledger = ledger
        self._test_name = str(test_name)
        if self._ledger is not None:
            # Reserve α under spend-on-reject policy; actual spend only if we reject H0
            self._ticket = self._ledger.open(test_name=self._test_name or "SPRT", alpha=self.alpha)
        else:
            self._ticket = None

    def update_llr(self, llr: float) -> SPRTResult:
        self._S += float(llr)
        self._n += 1
        # decision
        if self._S >= self.A:
            # accept H1 (reject H0)
            if self._ledger is not None and self._ticket is not None:
                self._ledger.commit(self._ticket, decision="reject", p_value=None, test_name=self._test_name)
                self._ticket = None
            res = SPRTResult(final=True, decision="accept_H1", S=self._S, A=self.A, B=self.B, n=self._n)
            if self.reset_on_decision:
                self.start(ledger=self._ledger, test_name=self._test_name)
            return res
        if self._S <= self.B:
            # accept H0
            if self._ledger is not None and self._ticket is not None:
                self._ledger.commit(self._ticket, decision="accept", p_value=None, test_name=self._test_name)
                self._ticket = None
            res = SPRTResult(final=True, decision="accept_H0", S=self._S, A=self.A, B=self.B, n=self._n)
            if self.reset_on_decision:
                self.start(ledger=self._ledger, test_name=self._test_name)
            return res
        return SPRTResult(final=False, decision="continue", S=self._S, A=self.A, B=self.B, n=self._n)


__all__ = ["SPRT", "SPRTResult", "gaussian_llr", "bernoulli_llr"]
