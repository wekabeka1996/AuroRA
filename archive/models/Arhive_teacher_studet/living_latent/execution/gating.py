from __future__ import annotations
from dataclasses import dataclass
from typing import Dict, Literal, Optional

Decision = Literal["PASS", "DERISK", "BLOCK"]

@dataclass
class GatingCfg:
    scale_map: Dict[str, float]
    hard_block_on_guard: bool = True
    min_notional: float = 0.0
    max_notional: float = 1e12

class RiskGate:
    def __init__(self, cfg: GatingCfg):
        self.cfg = cfg
        # basic validation
        for k in ("PASS","DERISK","BLOCK"):
            if k not in self.cfg.scale_map:
                raise ValueError(f"scale_map missing key {k}")

    def scale(self, decision: Decision, guards: Dict[str, bool], base_notional: float) -> float:
        """Compute recommended notional after gating.

        Parameters
        ----------
        decision : str
            Acceptance decision (PASS/DERISK/BLOCK)
        guards : dict[str,bool]
            Guard flags (surprisal, coverage, latency, width) True if violated
        base_notional : float
            Baseline notional (e.g., 1.0 for normalized sizing)
        Returns
        -------
        float
            Clipped recommended notional.
        """
        if decision not in self.cfg.scale_map:
            return 0.0
        scale = float(self.cfg.scale_map[decision])
        # hard block (any guard) overrides even PASS
        if self.cfg.hard_block_on_guard and any(guards.values()):
            scale = 0.0
        notional = base_notional * scale
        # clipping
        if notional == 0.0:
            return 0.0
        if notional < self.cfg.min_notional:
            notional = self.cfg.min_notional
        if notional > self.cfg.max_notional:
            notional = self.cfg.max_notional
        return notional

__all__ = ["GatingCfg","RiskGate","Decision"]

# --- Dwell / Hysteresis (AUR-GATE-601) ---

@dataclass
class DwellConfig:
    min_dwell_pass: int = 10
    min_dwell_derisk: int = 10
    min_dwell_block: int = 1  # allow faster escape from BLOCK by default

class DecisionHysteresis:
    """Simple dwell-based hysteresis wrapper for acceptance decisions.

    Maintains current stabilized state and enforces minimal dwell counts before
    allowing a transition away from that state. Tracks churn statistics.
    """
    def __init__(self, cfg: DwellConfig):
        self.cfg = cfg
        self._state: Decision = "PASS"
        self._dwell: int = 0
        self._transitions: int = 0
        self._decisions: int = 0
        # attempted transitions regardless of success (proposed_state != current_state)
        self._attempts: int = 0

    def update(self, proposed_state: Decision) -> Decision:
        """Update hysteresis with a newly proposed raw decision.

        If proposed_state equals current stabilized state we just extend dwell.
        Otherwise we count an attempt and only transition if minimum dwell satisfied.
        """
        self._decisions += 1
        if proposed_state == self._state:
            self._dwell += 1
            return self._state
        # new proposed different from current -> attempt
        self._attempts += 1
        need = {
            'PASS': self.cfg.min_dwell_pass,
            'DERISK': self.cfg.min_dwell_derisk,
            'BLOCK': self.cfg.min_dwell_block,
        }.get(self._state, 0)
        if self._dwell >= need:
            # allow transition
            self._state = proposed_state
            self._dwell = 0
            self._transitions += 1
        else:
            # hold state, increment dwell
            self._dwell += 1
        return self._state

    def churn_per_1k(self) -> float:
        if self._decisions == 0:
            return 0.0
        return 1000.0 * self._transitions / self._decisions

    def dwell_efficiency(self) -> float:
        """Return fraction of attempted transitions that succeeded.

        Defined as transitions / attempts; if no attempts yet, return 1.0 (neutral).
        """
        if self._attempts == 0:
            return 1.0
        return float(self._transitions) / float(self._attempts)

    @property
    def transitions(self) -> int:
        return self._transitions

    @property
    def decisions(self) -> int:
        return self._decisions

    @property
    def attempts(self) -> int:
        return self._attempts

def apply_risk_scale(notional: float, risk_scale: float) -> float:
    """Apply multiplicative risk_scale with clipping to [0,1]."""
    try:
        return max(0.0, float(notional) * float(min(1.0, max(0.0, risk_scale))))
    except Exception:
        return 0.0

def risk_scale_from_dro(penalty: float, k: float = 10.0, cap: float = 0.5) -> float:
    """Map DRO penalty -> additional risk scaling factor.

    Formula: scale = 1 / (1 + k * penalty)
    Then clamped into [cap, 1.0]. Lower bound cap (e.g. 0.5) prevents collapsing
    to near‑zero notional due to transient spikes while still derisking.

    Parameters
    ----------
    penalty : float
        DRO penalty (>=0). Non-finite -> returns 1.0 (neutral).
    k : float, default 10.0
        Sensitivity. Larger k -> stronger reduction per unit penalty.
    cap : float, default 0.5
        Minimum allowed scale (floor). Must be in (0,1].
    """
    try:
        if not (0 < cap <= 1.0):
            cap = 0.5
        p = float(penalty)
        if p <= 0 or not (p < float('inf')):
            return 1.0
        scale = 1.0 / (1.0 + k * p)
        if scale < cap:
            scale = cap
        if scale > 1.0:
            scale = 1.0
        return float(scale)
    except Exception:
        return 1.0

__all__ += ["DwellConfig","DecisionHysteresis","apply_risk_scale","risk_scale_from_dro"]
