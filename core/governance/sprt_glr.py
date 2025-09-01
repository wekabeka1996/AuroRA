from __future__ import annotations

"""
Composite SPRT/GLR - Sequential Hypothesis Testing with Unknown Variance
"""

import math
from dataclasses import dataclass
from typing import Optional, List
from enum import Enum


class SPRTOutcome(Enum):
    """SPRT decision outcomes."""
    ACCEPT_H0 = "accept_h0"
    ACCEPT_H1 = "accept_h1" 
    CONTINUE = "continue"
    TIMEOUT = "timeout"  # compat: не використовується у твоїй гілці


class AlphaSpendingPolicy(Enum):
    POCOCK = "pocock"
    OBF = "obf"
    BH_FDR = "bh_fdr"


@dataclass
class SPRTConfig:
    """Configuration for Sequential Probability Ratio Test."""
    mu0: float
    mu1: float
    alpha: float = 0.05
    beta: float = 0.20
    min_samples: int = 5
    max_samples: Optional[int] = None
    
    def __post_init__(self):
        if self.mu0 == self.mu1:
            raise ValueError("mu0 and mu1 must be different")
        if not 0 < self.alpha < 1:
            raise ValueError("alpha must be in (0, 1)")
        if not 0 < self.beta < 1:
            raise ValueError("beta must be in (0, 1)")
        if self.min_samples < 1:
            raise ValueError("min_samples must be >= 1")
        if self.max_samples is not None and self.max_samples < self.min_samples:
            raise ValueError("max_samples must be >= min_samples")
    
    @property
    def threshold_h0(self) -> float:
        return math.log(self.beta / (1 - self.alpha))
    
    @property
    def threshold_h1(self) -> float:
        return math.log((1 - self.beta) / self.alpha)


@dataclass
class SPRTState:
    """Internal state of SPRT computation."""
    n_samples: int = 0
    sum_x: float = 0.0
    sum_x2: float = 0.0
    llr: float = 0.0
    confidence: float = 0.0
    
    @property
    def mean(self) -> float:
        return self.sum_x / self.n_samples if self.n_samples > 0 else 0.0
    
    @property
    def variance(self) -> float:
        if self.n_samples <= 1:
            return 1.0
        return (self.sum_x2 - self.sum_x**2 / self.n_samples) / (self.n_samples - 1)
    
    @property
    def std_error(self) -> float:
        return math.sqrt(self.variance / self.n_samples) if self.n_samples > 0 else 1.0


@dataclass
class SPRTDecision:
    """SPRT decision result."""
    outcome: SPRTOutcome
    stop: bool
    llr: float
    confidence: float
    n_samples: int
    p_value: Optional[float] = None


class CompositeSPRT:
    """Composite Sequential Probability Ratio Test with unknown variance."""
    
    def __init__(self, config: SPRTConfig):
        self.config = config
        self.state = SPRTState()
        self.history: List[float] = []
        
    def update(self, observation: float) -> SPRTDecision:
        self.state.n_samples += 1
        self.state.sum_x += observation
        self.state.sum_x2 += observation**2
        self.history.append(observation)
        
        if self.state.n_samples < self.config.min_samples:
            return SPRTDecision(
                outcome=SPRTOutcome.CONTINUE,
                stop=False,
                llr=0.0,
                confidence=0.0,
                n_samples=self.state.n_samples
            )
        
        self.state.llr = self._compute_glr_llr()
        
        threshold_h0 = self.config.threshold_h0
        threshold_h1 = self.config.threshold_h1
        
        if self.state.llr <= threshold_h0:
            outcome = SPRTOutcome.ACCEPT_H0
            stop = True
            confidence = self._compute_confidence(self.state.llr, threshold_h0, "h0")
        elif self.state.llr >= threshold_h1:
            outcome = SPRTOutcome.ACCEPT_H1
            stop = True
            confidence = self._compute_confidence(self.state.llr, threshold_h1, "h1")
        else:
            outcome = SPRTOutcome.CONTINUE
            stop = False
            confidence = self._compute_confidence(self.state.llr, threshold_h0, "continue")
        
        if (self.config.max_samples is not None and 
            self.state.n_samples >= self.config.max_samples):
            stop = True
            if outcome == SPRTOutcome.CONTINUE:
                outcome = SPRTOutcome.ACCEPT_H0
                confidence = 0.5
        
        self.state.confidence = confidence
        
        return SPRTDecision(
            outcome=outcome,
            stop=stop,
            llr=self.state.llr,
            confidence=confidence,
            n_samples=self.state.n_samples,
            p_value=self._approximate_p_value() if stop else None
        )
    
    def _compute_glr_llr(self) -> float:
        n = self.state.n_samples
        x_bar = self.state.mean
        s2 = self.state.variance
        
        if s2 <= 0:
            s2 = 1e-6
        
        mu0, mu1 = self.config.mu0, self.config.mu1
        
        diff_h0 = (x_bar - mu0)**2
        diff_h1 = (x_bar - mu1)**2
        
        llr = (n / (2 * s2)) * (diff_h0 - diff_h1)
        
        return llr
    
    def _compute_confidence(self, llr: float, threshold: float, direction: str) -> float:
        threshold_h0 = self.config.threshold_h0
        threshold_h1 = self.config.threshold_h1
        
        if direction == "h0":
            excess = threshold_h0 - llr
            max_excess = abs(threshold_h0)
            confidence = min(1.0, max(0.5, excess / max_excess))
        elif direction == "h1":
            excess = llr - threshold_h1
            max_excess = abs(threshold_h1)
            confidence = min(1.0, max(0.5, excess / max_excess))
        else:
            dist_h0 = abs(llr - threshold_h0)
            dist_h1 = abs(llr - threshold_h1)
            min_dist = min(dist_h0, dist_h1)
            range_width = threshold_h1 - threshold_h0
            confidence = min_dist / range_width if range_width > 0 else 0.0
        
        return confidence
    
    def _approximate_p_value(self) -> float:
        if self.state.n_samples < 2:
            return 1.0
        
        x_bar = self.state.mean
        se = self.state.std_error
        
        t_stat = (x_bar - self.config.mu0) / se if se > 0 else 0.0
        p_value = 2 * (1 - self._normal_cdf(abs(t_stat)))
        
        return max(0.0, min(1.0, p_value))
    
    def _normal_cdf(self, z: float) -> float:
        return 0.5 * (1 + math.erf(z / math.sqrt(2)))
    
    def reset(self) -> None:
        self.state = SPRTState()
        self.history.clear()
    
    def get_summary(self) -> dict:
        return {
            "n_samples": self.state.n_samples,
            "mean": self.state.mean,
            "variance": self.state.variance,
            "llr": self.state.llr,
            "confidence": self.state.confidence,
            "thresholds": {
                "h0": self.config.threshold_h0,
                "h1": self.config.threshold_h1
            },
            "config": {
                "mu0": self.config.mu0,
                "mu1": self.config.mu1,
                "alpha": self.config.alpha,
                "beta": self.config.beta
            }
        }


# ---- Compatibility layer ----

SPRTResult = SPRTDecision  # compat alias


def create_sprt_pocock(alpha: float = 0.05, mu0: float = 0.0, mu1: float = 0.1) -> "CompositeSPRT":
    cfg = SPRTConfig(mu0=mu0, mu1=mu1, alpha=alpha)
    return CompositeSPRT(cfg)


def create_sprt_obf(alpha: float = 0.05, mu0: float = 0.0, mu1: float = 0.1) -> "CompositeSPRT":
    cfg = SPRTConfig(mu0=mu0, mu1=mu1, alpha=alpha)
    return CompositeSPRT(cfg)


def create_sprt_bh_fdr(alpha: float = 0.05, mu0: float = 0.0, mu1: float = 0.1) -> "CompositeSPRT":
    cfg = SPRTConfig(mu0=mu0, mu1=mu1, alpha=alpha)
    return CompositeSPRT(cfg)


__all__ = [
    "SPRTConfig", "SPRTState", "SPRTDecision", "SPRTOutcome", "CompositeSPRT",
    "SPRTResult", "AlphaSpendingPolicy",
    "create_sprt_pocock", "create_sprt_obf", "create_sprt_bh_fdr",
]
