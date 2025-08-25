from __future__ import annotations
from dataclasses import dataclass
from typing import Literal, Dict

Decision = Literal["PASS", "DERISK", "BLOCK"]

@dataclass
class HysteresisCfg:
    tau_pass_up: float
    tau_pass_down: float
    tau_derisk_up: float
    tau_derisk_down: float
    surprisal_guard_up: float
    surprisal_guard_down: float
    coverage_lower_bound_up: float
    coverage_lower_bound_down: float
    latency_p95_max_up_ms: float
    latency_p95_max_down_ms: float
    dwell_pass_up: int
    dwell_pass_down: int
    dwell_derisk_up: int
    dwell_derisk_down: int
    dwell_block_up: int
    dwell_block_down: int

    @staticmethod
    def from_dict(hys_cfg: dict | None, dwell_cfg: dict | None) -> 'HysteresisCfg':
        h = hys_cfg or {}
        d = dwell_cfg or {}
        return HysteresisCfg(
            tau_pass_up=h.get('tau_pass_up', 0.78),
            tau_pass_down=h.get('tau_pass_down', 0.72),
            tau_derisk_up=h.get('tau_derisk_up', 0.55),
            tau_derisk_down=h.get('tau_derisk_down', 0.48),
            surprisal_guard_up=h.get('surprisal_guard_up', 2.6),
            surprisal_guard_down=h.get('surprisal_guard_down', 2.4),
            coverage_lower_bound_up=h.get('coverage_lower_bound_up', 0.915),
            coverage_lower_bound_down=h.get('coverage_lower_bound_down', 0.885),
            latency_p95_max_up_ms=h.get('latency_p95_max_up_ms', 110.0),
            latency_p95_max_down_ms=h.get('latency_p95_max_down_ms', 130.0),
            dwell_pass_up=d.get('pass_up', 2),
            dwell_pass_down=d.get('pass_down', 1),
            dwell_derisk_up=d.get('derisk_up', 2),
            dwell_derisk_down=d.get('derisk_down', 1),
            dwell_block_up=d.get('block_up', 2),
            dwell_block_down=d.get('block_down', 2),
        )


class HysteresisGate:
    """Finite state machine with dwell counters and asymmetric thresholds.

    raw_decision: initial classification from Acceptance core (without hysteresis).
    apply(...) returns stabilized decision.
    """

    def __init__(self, cfg: HysteresisCfg):
        self.cfg = cfg
        self.current: Decision = "PASS"
        self._counters: Dict[str, int] = {
            'pass_up': 0, 'pass_down': 0,
            'derisk_up': 0, 'derisk_down': 0,
            'block_up': 0, 'block_down': 0
        }

    def reset(self):
        self.current = "PASS"
        for k in self._counters:
            self._counters[k] = 0

    def apply(self, raw: Decision, kappa_plus: float, p95_surprisal: float | None,
              coverage_ema: float | None, latency_p95: float | None, rel_width: float | None,
              guards: Dict[str, bool] | None = None) -> Decision:
        cfg = self.cfg
        guards = guards or {}

        # Evaluate guard breaches with hysteresis bands
        surprisal_guard = False
        if p95_surprisal is not None:
            if p95_surprisal > cfg.surprisal_guard_up:
                surprisal_guard = True
            elif p95_surprisal < cfg.surprisal_guard_down:
                surprisal_guard = False

        coverage_guard = False
        if coverage_ema is not None:
            if coverage_ema < cfg.coverage_lower_bound_down:
                coverage_guard = True
            elif coverage_ema >= cfg.coverage_lower_bound_up:
                coverage_guard = False

        latency_guard = False
        if latency_p95 is not None:
            if latency_p95 > cfg.latency_p95_max_down_ms:
                latency_guard = True
            elif latency_p95 <= cfg.latency_p95_max_up_ms:
                latency_guard = False

        guard_block = coverage_guard  # persistent low coverage escalates hardest
        guard_derisk = surprisal_guard or latency_guard

        # Determine target state from metrics (pre-dwell)
        target: Decision = self.current
        if guard_block:
            target = "BLOCK"
        elif guard_derisk:
            target = "DERISK" if self.current != "BLOCK" else self.current
        else:
            # kappa+ hysteresis layering
            if self.current == "PASS":
                if kappa_plus < cfg.tau_pass_down:
                    target = "DERISK"
            elif self.current == "DERISK":
                if kappa_plus >= cfg.tau_pass_up:
                    target = "PASS"
                elif kappa_plus < cfg.tau_derisk_down:
                    target = "BLOCK"
            elif self.current == "BLOCK":
                if kappa_plus >= cfg.tau_derisk_up:
                    target = "DERISK"
                if kappa_plus >= cfg.tau_pass_up:  # stronger condition for direct recovery
                    target = "PASS"

        # Dwell logic.
        if target != self.current:
            transition = f"{self._state_key(self.current)}_to_{self._state_key(target)}"
        else:
            transition = None

        decided = self.current
        if target == self.current:
            # reset opposite-oriented counters gradually
            self._zero_all()
            decided = self.current
        else:
            # increment appropriate dwell counter
            key = self._dwell_key(self.current, target)
            self._counters[key] += 1
            needed = self._dwell_needed(self.current, target)
            if self._counters[key] >= needed:
                decided = target
                self._zero_all()
                self.current = decided
        return decided

    # --------------- helpers --------------- #
    def _state_key(self, s: Decision) -> str:
        return s.lower()

    def _dwell_key(self, src: Decision, dst: Decision) -> str:
        if src == "PASS" and dst == "DERISK":
            return 'derisk_down'
        if src == "DERISK" and dst == "PASS":
            return 'derisk_up'
        if src == "DERISK" and dst == "BLOCK":
            return 'block_up'
        if src == "BLOCK" and dst == "DERISK":
            return 'block_down'
        if src == "PASS" and dst == "BLOCK":
            return 'block_up'
        if src == "BLOCK" and dst == "PASS":
            return 'block_down'
        return 'pass_up'

    def _dwell_needed(self, src: Decision, dst: Decision) -> int:
        c = self.cfg
        if src == "PASS" and dst == "DERISK":
            return c.dwell_derisk_down
        if src == "DERISK" and dst == "PASS":
            return c.dwell_derisk_up
        if src == "DERISK" and dst == "BLOCK":
            return c.dwell_block_up
        if src == "BLOCK" and dst == "DERISK":
            return c.dwell_block_down
        if src == "PASS" and dst == "BLOCK":
            return c.dwell_block_up
        if src == "BLOCK" and dst == "PASS":
            # require combined recovery: block_down + pass_up
            return c.dwell_block_down + c.dwell_pass_up
        return c.dwell_pass_up

    def _zero_all(self):
        for k in self._counters:
            self._counters[k] = 0

__all__ = ["HysteresisGate", "HysteresisCfg"]
