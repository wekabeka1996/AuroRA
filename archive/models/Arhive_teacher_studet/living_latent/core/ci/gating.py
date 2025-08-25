from __future__ import annotations
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal, List, Dict, Any, Optional
import json
import time
import os

State = Literal["observe","warn","watch","stable","cooldown","unknown"]

STATE_RANK: Dict[State,int] = {
    "observe": 0,
    "warn": 1,
    "watch": 2,
    "stable": 3,
    "cooldown": 4,
    "unknown": 9,
}

@dataclass
class MetricSpec:
    name: str
    source_key: str
    threshold_key: str
    relation: Literal["<=", ">=", "<", ">", "=="] = "<="
    hard_candidate: bool = False

@dataclass
class GatingEvent:
    run_id: str
    metric: str
    value: Optional[float]
    threshold: Optional[float]
    relation: str
    state_before: State
    state_after: State
    violation: bool
    consecutive_violations: int
    consecutive_ok: int
    message: str
    ts: float = field(default_factory=lambda: time.time())

class CIGatingStateMachine:
    """Soft runtime CI gating state machine (non-blocking).

    Tracks per-metric state transitions based on consecutive violations / passes.
    """
    def __init__(self, cfg: dict, metric_specs: List[MetricSpec], persistence_path: Path | None = None, metrics_exporter=None):
        self.cfg = cfg or {}
        self.metric_specs = metric_specs
        self.states: Dict[str, State] = {m.name: "observe" for m in metric_specs}
        self.viol_streak: Dict[str, int] = {m.name: 0 for m in metric_specs}
        self.ok_streak: Dict[str, int] = {m.name: 0 for m in metric_specs}
        self.watch_count: Dict[str, int] = {m.name: 0 for m in metric_specs}
        self.cooldown_left: Dict[str, int] = {m.name: 0 for m in metric_specs}
        self.persistence_path = persistence_path
        self.metrics_exporter = metrics_exporter  # optional Prometheus wrapper

        self.window_runs = int(self.cfg.get("window_runs", 5))
        self.enter_warn_runs = int(self.cfg.get("enter_warn_runs", 2))
        self.exit_warn_runs = int(self.cfg.get("exit_warn_runs", 3))
        self.enter_watch_runs = int(self.cfg.get("enter_watch_runs", 1))
        self.cooldown_runs = int(self.cfg.get("cooldown_runs", 3))

    # --- Helpers ---
    @staticmethod
    def _get_dotted(src: Dict[str, Any], dotted: str) -> Any:
        cur: Any = src
        for part in dotted.split('.'):
            if not isinstance(cur, dict):
                return None
            cur = cur.get(part)
            if cur is None:
                return None
        return cur

    @staticmethod
    def _compare(val: float, thr: float, rel: str) -> bool:
        if val is None or thr is None:
            return False
        try:
            if rel == '<=': return val <= thr
            if rel == '>=': return val >= thr
            if rel == '<': return val < thr
            if rel == '>': return val > thr
            if rel == '==': return val == thr
        except Exception:
            return False
        return False

    def _persist_event(self, ev: GatingEvent):
        if not self.persistence_path:
            return
        try:
            self.persistence_path.parent.mkdir(parents=True, exist_ok=True)
            with self.persistence_path.open('a', encoding='utf-8') as f:
                f.write(json.dumps(ev.__dict__) + '\n')
        except Exception:
            pass

    def evaluate_batch(self, run_id: str, summary: Dict[str, Any], thresholds: Dict[str, Any]) -> List[GatingEvent]:
        """Evaluate metrics producing soft gating events.

        Also determines whether any metric marked hard_candidate AND having cfg.hard_enabled causes
        a hard gating failure (immediate build break suggestion). We do not raise SystemExit here
        (caller decides), but we annotate events via message tag [CI-GATING][HARD] when violation.
        """
        events: List[GatingEvent] = []
        hard_enabled_global = bool(self.cfg.get('hard_enabled', False))
        
        # OPERATIONS-SAFETY: panic file disables hard gating
        panic_file = self.cfg.get('panic_file')
        panic_active = False
        if panic_file and os.path.exists(panic_file):
            hard_enabled_global = False
            panic_active = True
            
        # Optional per-metric hard enable metadata (flat keys under thresholds -> hard_meta[flat_key].hard_enabled)
        hard_meta = {}
        try:
            hard_meta = thresholds.get('hard_meta', {}) if isinstance(thresholds, dict) else {}
        except Exception:
            hard_meta = {}
        hard_fail_metrics: list[str] = []
        
        for spec in self.metric_specs:
            before = self.states.get(spec.name, 'observe')
            value = self._get_dotted(summary, spec.source_key)
            thr = self._get_dotted(thresholds, spec.threshold_key)
            violation: bool
            unknown = False
            if value is None or thr is None:
                violation = False
                unknown = True
            else:
                # violation = NOT meeting relation (relation expresses acceptable region)
                ok = self._compare(float(value), float(thr), spec.relation)
                violation = not ok

            # Update streaks
            if unknown:
                self.viol_streak[spec.name] = 0
                self.ok_streak[spec.name] = 0
            elif violation:
                self.viol_streak[spec.name] += 1
                self.ok_streak[spec.name] = 0
            else:
                self.ok_streak[spec.name] += 1
                self.viol_streak[spec.name] = 0

            after = before
            # Transition logic
            if unknown:
                after = 'unknown'
            else:
                if before in ('observe','stable'):
                    if violation and self.viol_streak[spec.name] >= self.enter_warn_runs:
                        after = 'warn'
                        self.watch_count[spec.name] = self.enter_watch_runs
                elif before == 'warn':
                    if not violation and self.ok_streak[spec.name] >= self.exit_warn_runs:
                        after = 'stable'
                        self.cooldown_left[spec.name] = self.cooldown_runs
                    elif violation:
                        # stay warn, refresh watch
                        self.watch_count[spec.name] = self.enter_watch_runs
                elif before == 'stable':
                    if violation and self.viol_streak[spec.name] >= self.enter_warn_runs:
                        after = 'warn'
                        self.watch_count[spec.name] = self.enter_watch_runs
                elif before == 'watch':
                    # treat watch as sub-phase of warn for now
                    if not violation and self.ok_streak[spec.name] >= self.exit_warn_runs:
                        after = 'stable'
                        self.cooldown_left[spec.name] = self.cooldown_runs
                elif before == 'cooldown':
                    if self.cooldown_left[spec.name] > 0:
                        self.cooldown_left[spec.name] -= 1
                    if self.cooldown_left[spec.name] <= 0:
                        after = 'observe'
                    if violation:
                        after = 'warn'
                        self.watch_count[spec.name] = self.enter_watch_runs

            # watch sub-phase decrement
            if after == 'warn' and self.watch_count[spec.name] > 0:
                self.watch_count[spec.name] -= 1
                if self.watch_count[spec.name] == 0:
                    after = 'watch'

            self.states[spec.name] = after

            message = (f"[CI-GATING] metric={spec.name} value={value} threshold={thr} relation={spec.relation} "
                       f"state:{before}->{after} violation={violation} run={run_id}")
            # Determine dynamic hard flag: global + per-metric meta must both allow
            flat_key = spec.threshold_key.split('.')[-1]
            hard_meta_block = hard_meta.get(flat_key) if isinstance(hard_meta, dict) else None
            hard_enabled_meta = bool(hard_meta_block.get('hard_enabled')) if isinstance(hard_meta_block, dict) else False
            hard_reason = hard_meta_block.get('hard_reason') if isinstance(hard_meta_block, dict) else None
            hard_active = hard_enabled_global and spec.hard_candidate and hard_enabled_meta
            if panic_active and violation and spec.hard_candidate:
                # Panic disables hard gating, log event
                message = f"[PANIC] hard gating disabled {message}"
            elif violation and hard_active:
                hard_fail_metrics.append(spec.name)
                tag_extra = f" reason={hard_reason}" if hard_reason else ""
                message = f"[CI-GATING][HARD]{tag_extra} {message}"
            ev = GatingEvent(
                run_id=run_id,
                metric=spec.name,
                value=float(value) if isinstance(value,(int,float)) else None,
                threshold=float(thr) if isinstance(thr,(int,float)) else None,
                relation=spec.relation,
                state_before=before, state_after=after,
                violation=violation, consecutive_violations=self.viol_streak[spec.name],
                consecutive_ok=self.ok_streak[spec.name], message=message
            )
            events.append(ev)
            self._persist_event(ev)
            # Export Prometheus metrics if provided
            if self.metrics_exporter is not None:
                try:
                    self.metrics_exporter.set_ci_gating_state(spec.name, after)
                    if value is not None:
                        self.metrics_exporter.set_ci_gating_value(spec.name, float(value))
                    if thr is not None:
                        self.metrics_exporter.set_ci_gating_threshold(spec.name, float(thr))
                    if violation:
                        self.metrics_exporter.inc_ci_gating_violation(spec.name)
                except Exception:
                    pass
        # If any hard failures flagged, append a synthetic summary event (no state change) for visibility
        if hard_fail_metrics:
            note = GatingEvent(
                run_id=run_id,
                metric='__hard_gating__',
                value=None, threshold=None, relation='<=',
                state_before='unknown', state_after='unknown',
                violation=True, consecutive_violations=0, consecutive_ok=0,
                message=f"[CI-GATING][HARD] metrics_failed={','.join(sorted(hard_fail_metrics))} hard_enabled=1"
            )
            events.append(note)
            self._persist_event(note)
        return events

    def any_hard_failure(self, events: List[GatingEvent]) -> bool:
        """Return True if a hard gating failure was recorded in events."""
        for ev in events:
            if '[CI-GATING][HARD]' in ev.message and ev.metric != '__hard_gating__':
                return True
        return False

__all__ = [
    'MetricSpec','GatingEvent','CIGatingStateMachine','State','STATE_RANK'
]
