"""
Anti-flood logger for Aurora events.

Prevents log-storm by deduplicating events within time windows and applying 
sampling rates to high-frequency events like POLICY.DECISION skip_open.
"""

import time
import json
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
from collections import defaultdict
from pathlib import Path


@dataclass
class SamplingRule:
    """Rule for sampling specific events."""
    match: str  # Format: "EVENT_TYPE:reason" or "EVENT_TYPE"
    sample_every: int  # Only log every N-th occurrence
    
    def matches(self, event_type: str, reason: Optional[str] = None) -> bool:
        """Check if this rule matches the event."""
        if ':' in self.match:
            type_part, reason_part = self.match.split(':', 1)
            return event_type == type_part and reason == reason_part
        else:
            return event_type == self.match


class AntiFloodLogger:
    """
    Anti-flood wrapper for event logging that prevents disk spam.
    
    Features:
    - Deduplication window: skip identical events within time window
    - Sampling: only log every N-th occurrence of high-frequency events
    - Metrics: track dropped/sampled counts for Prometheus
    """
    
    def __init__(
        self,
        dedup_window_ms: int = 500,
        sampling_rules: Optional[List[SamplingRule]] = None,
        metrics_callback: Optional[callable] = None
    ):
        self.dedup_window_ms = dedup_window_ms
        self.sampling_rules = sampling_rules or []
        self.metrics_callback = metrics_callback  # Called with (event_type, action, count)
        
        # Dedup state: key -> last_timestamp_ms
        self.dedup_cache: Dict[str, float] = {}
        
        # Sampling state: key -> (count, last_logged_count)
        self.sampling_state: Dict[str, tuple[int, int]] = defaultdict(lambda: (0, 0))
        
        # Metrics counters
        self.dropped_total = defaultdict(int)
        self.sampled_total = defaultdict(int)
    
    def _make_dedup_key(self, event_type: str, payload: Dict[str, Any]) -> str:
        """Create deduplication key from event type and key payload fields."""
        # Include critical fields that make events unique
        key_fields = []
        
        if event_type == "POLICY.DECISION":
            # Handle both direct decision field and details.decision field
            decision = payload.get('decision', '')
            if not decision:
                details = payload.get('details', {})
                decision = details.get('decision', '')
            reasons = payload.get('reasons', [])
            key_fields = [decision, str(sorted(reasons) if isinstance(reasons, list) else reasons)]
        elif event_type == "PARENT_GATE.EVAL":
            outcome = payload.get('outcome', '')
            reason = payload.get('reason', '')
            key_fields = [outcome, reason]
        elif event_type == "EXPECTED_NET_REWARD_GATE":
            outcome = payload.get('outcome', '')
            threshold = payload.get('threshold_bps', '')
            key_fields = [outcome, str(threshold)]
        else:
            # Generic fallback - use first few payload values
            vals = list(str(v) for v in list(payload.values())[:3])
            key_fields = vals
            
        return f"{event_type}|{'|'.join(key_fields)}"
    
    def _should_deduplicate(self, dedup_key: str, now_ms: float) -> bool:
        """Check if event should be deduplicated (skipped)."""
        if dedup_key in self.dedup_cache:
            last_ts = self.dedup_cache[dedup_key]
            if now_ms - last_ts < self.dedup_window_ms:
                return True  # Skip - too soon
        
        # Update cache
        self.dedup_cache[dedup_key] = now_ms
        return False
    
    def _should_sample(self, event_type: str, payload: Dict[str, Any]) -> bool:
        """Check if event should be sampled (potentially skipped)."""
        # Find matching sampling rule
        matching_rule = None
        for rule in self.sampling_rules:
            reason = None
            if event_type == "POLICY.DECISION":
                reasons_list = payload.get('reasons', [])
                if reasons_list:
                    reason = reasons_list[0]
                else:
                    # Look for decision in details (for trap events)
                    details = payload.get('details', {})
                    reason = details.get('decision', payload.get('decision', ''))
            elif event_type == "RISK.DENY":
                reason = payload.get('reason', '')
            
            if rule.matches(event_type, reason):
                matching_rule = rule
                break
        
        if not matching_rule:
            return True  # No sampling rule - always log
        
        # Apply sampling
        sample_key = f"{event_type}:{matching_rule.match}"
        count, last_logged = self.sampling_state[sample_key]
        count += 1
        self.sampling_state[sample_key] = (count, last_logged)
        
        if count - last_logged >= matching_rule.sample_every:
            # Time to log this one
            self.sampling_state[sample_key] = (count, count)
            return True
        else:
            # Skip this occurrence
            self.sampled_total[sample_key] += 1
            if self.metrics_callback:
                self.metrics_callback(event_type, 'sampled', 1)
            return False
    
    def should_log(self, event_type: str, payload: Dict[str, Any]) -> bool:
        """
        Main filter: check if event should be logged.
        
        Returns True if event should be written to disk, False if dropped/sampled.
        """
        now_ms = time.time() * 1000
        
        # Check deduplication
        dedup_key = self._make_dedup_key(event_type, payload)
        if self._should_deduplicate(dedup_key, now_ms):
            self.dropped_total[event_type] += 1
            if self.metrics_callback:
                self.metrics_callback(event_type, 'dropped', 1)
            return False
        
        # Check sampling
        if not self._should_sample(event_type, payload):
            return False
        
        return True
    
    def get_metrics(self) -> Dict[str, Any]:
        """Get current metrics for Prometheus export."""
        return {
            'dropped_total': dict(self.dropped_total),
            'sampled_total': dict(self.sampled_total),
            'dedup_cache_size': len(self.dedup_cache),
            'sampling_state_size': len(self.sampling_state)
        }
    
    def cleanup_old_entries(self, max_age_ms: float = 60000) -> None:
        """Clean up old dedup cache entries to prevent memory leak."""
        now_ms = time.time() * 1000
        cutoff = now_ms - max_age_ms
        
        old_keys = [k for k, ts in self.dedup_cache.items() if ts < cutoff]
        for k in old_keys:
            del self.dedup_cache[k]


def create_default_anti_flood_logger(
    dedup_window_ms: int = 500,
    metrics_callback: Optional[callable] = None
) -> AntiFloodLogger:
    """Create anti-flood logger with default sampling rules for Aurora."""
    
    default_rules = [
        SamplingRule("POLICY.DECISION:skip_open", sample_every=1),  # Reduced for testing
        SamplingRule("RISK.DENY:WHY_NEGATIVE_EDGE", sample_every=1),  # Reduced for testing
        SamplingRule("PARENT_GATE.EVAL:parent_cooloff", sample_every=1),  # Reduced for testing
        SamplingRule("EXPECTED_NET_REWARD_GATE:deny", sample_every=1),  # Reduced for testing
    ]
    
    return AntiFloodLogger(
        dedup_window_ms=dedup_window_ms,
        sampling_rules=default_rules,
        metrics_callback=metrics_callback
    )


class AntiFloodJSONLWriter:
    """JSONL writer with anti-flood protection."""
    
    def __init__(self, path: Path, anti_flood: AntiFloodLogger):
        self.path = Path(path)
        self.anti_flood = anti_flood
        
    def write_event(self, event_type: str, payload: Dict[str, Any], **extra_fields) -> bool:
        """
        Write event to JSONL if not filtered by anti-flood.
        
        Returns True if written, False if dropped/sampled.
        """
        if not self.anti_flood.should_log(event_type, payload):
            return False
        
        # Construct full record
        record = {
            'ts': int(time.time() * 1000),
            'type': event_type,
            'payload': payload,
            **extra_fields
        }
        
        # Write to file
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open('a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False) + '\n')
        
        return True