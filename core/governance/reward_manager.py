"""
Reward Manager with Trail Logic for Router Decisions
===================================================

Enhanced reward management system that tracks decision trails and manages
reward attribution for routing decisions with proper negative reward handling.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any


@dataclass
class Decision:
    """Enhanced Decision class with trail reward tracking."""
    route: str                 # "maker" | "taker" | "deny"
    why_code: str              # e.g. "OK_ROUTE_MAKER", "OK_ROUTE_TAKER", "WHY_UNATTRACTIVE"
    scores: dict[str, float]
    trail_reward: float | None = None  # New field for reward tracking


@dataclass
class RewardTrail:
    """Trail of rewards for decision tracking."""
    decision_id: str
    timestamp: float
    route: str
    why_code: str
    initial_reward: float
    current_reward: float
    trail_updates: list[dict[str, Any]] = field(default_factory=list)
    is_active: bool = True


class RewardManager:
    """
    Enhanced Reward Manager with trail tracking and negative reward handling.
    
    Features:
    - Decision trail tracking
    - Negative reward protection
    - Reward attribution across time
    - Performance analytics
    """

    def __init__(self, config: dict[str, Any] = None):
        self.config = config or {}
        self.trails: dict[str, RewardTrail] = {}
        self.negative_reward_threshold = float(self.config.get("negative_reward_threshold", -0.5))
        self.trail_decay_factor = float(self.config.get("trail_decay_factor", 0.95))
        self.max_trail_age_sec = int(self.config.get("max_trail_age_sec", 3600))

    def create_decision_with_trail(self,
                                   route: str,
                                   why_code: str,
                                   scores: dict[str, float],
                                   initial_reward: float = 0.0) -> Decision:
        """Create a new decision with reward trail tracking."""

        # Apply negative reward protection
        protected_reward = self._apply_negative_reward_protection(initial_reward)

        decision = Decision(
            route=route,
            why_code=why_code,
            scores=scores.copy(),
            trail_reward=protected_reward
        )

        # Create trail entry
        decision_id = f"{route}_{why_code}_{int(time.time()*1000)}"
        trail = RewardTrail(
            decision_id=decision_id,
            timestamp=time.time(),
            route=route,
            why_code=why_code,
            initial_reward=initial_reward,
            current_reward=protected_reward
        )

        self.trails[decision_id] = trail

        # Clean old trails
        self._cleanup_old_trails()

        return decision

    def update_trail_reward(self, decision_id: str, new_reward: float, metadata: dict[str, Any] = None) -> bool:
        """Update reward for an existing decision trail."""
        if decision_id not in self.trails:
            return False

        trail = self.trails[decision_id]
        if not trail.is_active:
            return False

        # Apply decay factor
        decayed_reward = new_reward * self.trail_decay_factor

        # Apply negative reward protection
        protected_reward = self._apply_negative_reward_protection(decayed_reward)

        # Update trail
        trail.current_reward = protected_reward
        trail.trail_updates.append({
            "timestamp": time.time(),
            "raw_reward": new_reward,
            "decayed_reward": decayed_reward,
            "protected_reward": protected_reward,
            "metadata": metadata or {}
        })

        return True

    def close_trail(self, decision_id: str, final_reward: float = None) -> RewardTrail | None:
        """Close a decision trail and return final summary."""
        if decision_id not in self.trails:
            return None

        trail = self.trails[decision_id]
        trail.is_active = False

        if final_reward is not None:
            trail.current_reward = self._apply_negative_reward_protection(final_reward)

        return trail

    def get_trail_summary(self, decision_id: str) -> dict[str, Any] | None:
        """Get summary of a decision trail."""
        if decision_id not in self.trails:
            return None

        trail = self.trails[decision_id]
        age_sec = time.time() - trail.timestamp

        return {
            "decision_id": decision_id,
            "route": trail.route,
            "why_code": trail.why_code,
            "age_sec": age_sec,
            "initial_reward": trail.initial_reward,
            "current_reward": trail.current_reward,
            "total_updates": len(trail.trail_updates),
            "is_active": trail.is_active,
            "reward_improvement": trail.current_reward - trail.initial_reward
        }

    def get_active_trails(self) -> list[dict[str, Any]]:
        """Get summaries of all active trails."""
        return [
            self.get_trail_summary(decision_id)
            for decision_id, trail in self.trails.items()
            if trail.is_active
        ]

    def get_performance_metrics(self) -> dict[str, Any]:
        """Get overall performance metrics across all trails."""
        if not self.trails:
            return {"total_decisions": 0}

        total_trails = len(self.trails)
        active_trails = len([t for t in self.trails.values() if t.is_active])

        rewards = [t.current_reward for t in self.trails.values()]
        avg_reward = sum(rewards) / len(rewards) if rewards else 0.0

        route_counts = {}
        for trail in self.trails.values():
            route_counts[trail.route] = route_counts.get(trail.route, 0) + 1

        return {
            "total_decisions": total_trails,
            "active_trails": active_trails,
            "avg_reward": avg_reward,
            "route_distribution": route_counts,
            "negative_rewards_protected": len([r for r in rewards if r == self.negative_reward_threshold])
        }

    def _apply_negative_reward_protection(self, reward: float) -> float:
        """Apply protection against excessive negative rewards."""
        if reward < self.negative_reward_threshold:
            return self.negative_reward_threshold
        return reward

    def _cleanup_old_trails(self):
        """Remove trails older than max_trail_age_sec."""
        current_time = time.time()
        to_remove = []

        for decision_id, trail in self.trails.items():
            if current_time - trail.timestamp > self.max_trail_age_sec:
                to_remove.append(decision_id)

        for decision_id in to_remove:
            del self.trails[decision_id]

    def export_trails_json(self, filepath: str):
        """Export all trails to JSON file for analysis."""
        export_data = {
            "timestamp": time.time(),
            "config": self.config,
            "trails": {}
        }

        for decision_id, trail in self.trails.items():
            export_data["trails"][decision_id] = {
                "decision_id": trail.decision_id,
                "timestamp": trail.timestamp,
                "route": trail.route,
                "why_code": trail.why_code,
                "initial_reward": trail.initial_reward,
                "current_reward": trail.current_reward,
                "trail_updates": trail.trail_updates,
                "is_active": trail.is_active
            }

        with open(filepath, 'w') as f:
            json.dump(export_data, f, indent=2)


# Backward compatibility factory function
def create_enhanced_decision(route: str,
                           why_code: str,
                           scores: dict[str, float],
                           reward_manager: RewardManager = None,
                           initial_reward: float = 0.0) -> Decision:
    """Factory function for creating enhanced decisions with trail tracking."""
    if reward_manager:
        return reward_manager.create_decision_with_trail(route, why_code, scores, initial_reward)
    else:
        return Decision(route=route, why_code=why_code, scores=scores, trail_reward=initial_reward)
