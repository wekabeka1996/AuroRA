from __future__ import annotations

import math
from typing import Dict, Any
from collections import deque
import time


class ParentGate:
    """Parent→Child gate. Evaluates parent symbol movement to allow/deny child trades."""

    def __init__(self, cfg: Dict[str, Any]):
        self.cfg = cfg or {}
        self.lookback = int(self.cfg.get('lookback_s', 120))
        self.z_threshold = float(self.cfg.get('z_threshold', 0.75))
        self.align_sign = bool(self.cfg.get('align_sign', True))
        self.max_spread_bps = float(self.cfg.get('max_spread_bps', 50.0))
        self.cooloff_s = float(self.cfg.get('cooloff_s', 30.0))
        self.parent = self.cfg.get('parent')
        self.child = self.cfg.get('child')
        # simple in-memory recent returns queue per parent
        self._values = deque()
        self._last_deny_ts = 0.0

    def _zscore(self, arr):
        if not arr:
            return 0.0
        mean = sum(arr) / len(arr)
        var = sum((x - mean) ** 2 for x in arr) / len(arr)
        sd = math.sqrt(var) if var > 0 else 0.0
        return (arr[-1] - mean) / sd if sd > 0 else 0.0

    def record_parent_return(self, ret: float, ts: float = None):
        ts = ts or time.time()
        # maintain fixed-length lookback list approximated by count
        self._values.append(ret)
        # cap by seconds ~ using sample rate ~1 per sec
        while len(self._values) > max(1, int(self.lookback)):
            self._values.popleft()

    def evaluate(self, parent_ret: float, child_direction: int, child_spread_bps: float) -> Dict[str, Any]:
        """Evaluate whether to allow child trade.

        child_direction: +1 for buy, -1 for sell
        Returns dict with outcome and diagnostics.
        """
        z = self._zscore(list(self._values) + [parent_ret])
        aligned = (child_direction >= 0 and parent_ret >= 0) or (child_direction < 0 and parent_ret < 0)

        # respect cooloff
        now = time.time()
        cooldown_remaining_s = max(0, self.cooloff_s - (now - self._last_deny_ts))
        
        if cooldown_remaining_s > 0:
            outcome = 'deny'
            reason = 'parent_cooloff'
            return {
                'outcome': outcome, 
                'z': z, 
                'aligned': aligned, 
                'child_spread_bps': child_spread_bps, 
                'reason': reason,
                'cooldown_remaining_s': cooldown_remaining_s
            }

        # spread check
        if child_spread_bps is not None and child_spread_bps > self.max_spread_bps:
            self._last_deny_ts = now
            outcome = 'deny'
            reason = 'child_spread'
            return {'outcome': outcome, 'z': z, 'aligned': aligned, 'child_spread_bps': child_spread_bps, 'reason': reason, 'cooldown_remaining_s': 0}

        # weak parent
        if abs(z) < self.z_threshold:
            self._last_deny_ts = now
            outcome = 'deny'
            reason = 'parent_weak'
            return {'outcome': outcome, 'z': z, 'aligned': aligned, 'child_spread_bps': child_spread_bps, 'reason': reason, 'cooldown_remaining_s': 0}

        # misalignment
        if self.align_sign and not aligned:
            self._last_deny_ts = now
            outcome = 'deny'
            reason = 'parent_misaligned'
            return {'outcome': outcome, 'z': z, 'aligned': aligned, 'child_spread_bps': child_spread_bps, 'reason': reason, 'cooldown_remaining_s': 0}

        # otherwise allow
        return {'outcome': 'allow', 'z': z, 'aligned': aligned, 'child_spread_bps': child_spread_bps, 'cooldown_remaining_s': 0}


def create_parent_gate(cfg: Dict[str, Any]) -> ParentGate:
    return ParentGate(cfg)
