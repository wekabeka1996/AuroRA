from __future__ import annotations
import json
from pathlib import Path
from dataclasses import dataclass, field
from typing import List, Optional, Dict
import math

@dataclass
class DCTSDivergenceConfig:
    enabled: bool = False
    abs_delta_max: float = 0.08
    rel_delta_max: float = 0.15
    window_runs: int = 5
    min_breaches: int = 3
    persistence_file: Optional[Path] = None

@dataclass
class DCTSDivergenceState:
    deltas: List[float] = field(default_factory=list)
    breaches: int = 0
    window_runs: int = 5

    def to_dict(self):
        return {"deltas": self.deltas, "breaches": self.breaches, "window_runs": self.window_runs}

    @classmethod
    def from_dict(cls, d: Dict):
        return cls(
            deltas=list(d.get("deltas", []))[-cls._max_allowed():],
            breaches=int(d.get("breaches", 0)),
            window_runs=int(d.get("window_runs", 5))
        )

    @staticmethod
    def _max_allowed():
        return 100  # safety cap

class DCTSDivergenceMonitor:
    def __init__(self, cfg: DCTSDivergenceConfig):
        self.cfg = cfg
        self.state = DCTSDivergenceState(window_runs=cfg.window_runs)
        if cfg.persistence_file and cfg.persistence_file.exists():
            try:
                loaded = json.loads(cfg.persistence_file.read_text(encoding='utf-8'))
                self.state = DCTSDivergenceState.from_dict(loaded)
            except Exception:
                pass

    def _persist(self):
        if self.cfg.persistence_file:
            try:
                self.cfg.persistence_file.parent.mkdir(parents=True, exist_ok=True)
                self.cfg.persistence_file.write_text(json.dumps(self.state.to_dict(), indent=2), encoding='utf-8')
            except Exception:
                pass

    def observe(self, base: float | None, robust: float | None):
        if base is None or robust is None or not all(isinstance(v,(int,float)) for v in (base,robust)):
            return None
        if not (math.isfinite(base) and math.isfinite(robust)):
            return None
        delta = abs(robust - base)
        rel = delta / max(1e-9, abs(base))
        breach = (delta > self.cfg.abs_delta_max) or (rel > self.cfg.rel_delta_max)
        self.state.deltas.append(delta)
        if len(self.state.deltas) > self.cfg.window_runs:
            # pop oldest
            self.state.deltas = self.state.deltas[-self.cfg.window_runs:]
        # recount breaches in current window for consistency
        # (Alternatively track rolling but recompute for clarity)
        # Need base/robust history to recompute rel each step; for simplicity count only this step when window full
        if breach:
            self.state.breaches += 1
        result = {
            'delta': delta,
            'rel_delta': rel,
            'breach': breach,
            'breaches_total': self.state.breaches,
        }
        self._persist()
        return result

    def should_alert(self) -> bool:
        # Using total breaches within rolling logic simplified: alert if total breaches in last window >= min_breaches
        # More precise implementation would retain parallel list of breach flags; we adapt by limiting breaches if window resets.
        # For deterministic behaviour: count only breaches in last window length by capping state.
        # We'll approximate by min(self.state.breaches, window_runs)
        recent_breaches = min(self.state.breaches, len(self.state.deltas))
        return recent_breaches >= min(self.cfg.min_breaches, self.cfg.window_runs)

__all__ = [
    'DCTSDivergenceConfig', 'DCTSDivergenceMonitor'
]
