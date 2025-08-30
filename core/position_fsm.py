from __future__ import annotations

"""
Position Lifecycle — Finite State Machine v1.0
==============================================

Manages position lifecycle with proper state transitions:
FLAT → ENTRY_PENDING → OPEN → {SCALE_IN_PENDING ↔ OPEN} → REDUCE_PENDING → CLOSED

Events: edge_change, fill(partial/full), ttl_expired, trail_hit, tp_hit, risk_deny, exchange_reject, governance_kill

Invariant: Any deny from Risk/Governance zeros target-size; Execution nets to 0 on deny.
"""

from dataclasses import dataclass
from typing import Literal, Optional, Dict, Any, List
from enum import Enum
import time


class PositionState(Enum):
    """Position lifecycle states"""
    FLAT = "FLAT"
    ENTRY_PENDING = "ENTRY_PENDING"
    OPEN = "OPEN"
    SCALE_IN_PENDING = "SCALE_IN_PENDING"
    REDUCE_PENDING = "REDUCE_PENDING"
    CLOSED = "CLOSED"


class PositionEvent(Enum):
    """Events that can trigger state transitions"""
    EDGE_CHANGE = "edge_change"
    FILL_PARTIAL = "fill_partial"
    FILL_FULL = "fill_full"
    TTL_EXPIRED = "ttl_expired"
    TRAIL_HIT = "trail_hit"
    TP_HIT = "tp_hit"
    RISK_DENY = "risk_deny"
    EXCHANGE_REJECT = "exchange_reject"
    GOVERNANCE_KILL = "governance_kill"
    SCALE_SIGNAL = "scale_signal"
    REDUCE_SIGNAL = "reduce_signal"


@dataclass
class PositionData:
    """Position state data"""
    position_id: str
    symbol: str
    side: Literal['BUY', 'SELL']
    target_qty: float
    current_qty: float = 0.0
    entry_price: Optional[float] = None
    current_price: Optional[float] = None
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    fees_paid: float = 0.0
    state: PositionState = PositionState.FLAT
    created_ts: int = 0
    last_update_ts: int = 0
    ttl_seconds: Optional[int] = None
    exit_reason: Optional[str] = None
    
    def __post_init__(self):
        if self.created_ts == 0:
            self.created_ts = int(time.time())
        if self.last_update_ts == 0:
            self.last_update_ts = int(time.time())


@dataclass
class TransitionResult:
    """Result of a state transition"""
    success: bool
    new_state: PositionState
    actions: List[str]  # Actions to take (e.g., ["cancel_orders", "flatten_position"])
    reason: str
    metadata: Optional[Dict[str, Any]] = None
    
    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


class PositionFSM:
    """Finite State Machine for position lifecycle management"""
    
    def __init__(self):
        self._transitions = self._build_transition_table()
    
    def _build_transition_table(self) -> Dict[PositionState, Dict[PositionEvent, PositionState]]:
        """Build the state transition table"""
        return {
            PositionState.FLAT: {
                PositionEvent.EDGE_CHANGE: PositionState.ENTRY_PENDING,
            },
            PositionState.ENTRY_PENDING: {
                PositionEvent.FILL_PARTIAL: PositionState.ENTRY_PENDING,  # Stay pending until full entry
                PositionEvent.FILL_FULL: PositionState.OPEN,
                PositionEvent.RISK_DENY: PositionState.FLAT,
                PositionEvent.EXCHANGE_REJECT: PositionState.FLAT,
                PositionEvent.GOVERNANCE_KILL: PositionState.FLAT,
                PositionEvent.TTL_EXPIRED: PositionState.FLAT,
            },
            PositionState.OPEN: {
                PositionEvent.SCALE_SIGNAL: PositionState.SCALE_IN_PENDING,
                PositionEvent.REDUCE_SIGNAL: PositionState.REDUCE_PENDING,
                PositionEvent.TP_HIT: PositionState.REDUCE_PENDING,
                PositionEvent.TRAIL_HIT: PositionState.REDUCE_PENDING,
                PositionEvent.TTL_EXPIRED: PositionState.REDUCE_PENDING,
                PositionEvent.RISK_DENY: PositionState.REDUCE_PENDING,
                PositionEvent.GOVERNANCE_KILL: PositionState.REDUCE_PENDING,
            },
            PositionState.SCALE_IN_PENDING: {
                PositionEvent.FILL_PARTIAL: PositionState.SCALE_IN_PENDING,
                PositionEvent.FILL_FULL: PositionState.OPEN,
                PositionEvent.RISK_DENY: PositionState.OPEN,  # Revert to OPEN without scale
                PositionEvent.EXCHANGE_REJECT: PositionState.OPEN,
                PositionEvent.GOVERNANCE_KILL: PositionState.REDUCE_PENDING,
                PositionEvent.TTL_EXPIRED: PositionState.OPEN,
            },
            PositionState.REDUCE_PENDING: {
                PositionEvent.FILL_PARTIAL: PositionState.REDUCE_PENDING,
                PositionEvent.FILL_FULL: PositionState.CLOSED,
                PositionEvent.RISK_DENY: PositionState.FLAT,  # Emergency flatten
                PositionEvent.EXCHANGE_REJECT: PositionState.REDUCE_PENDING,  # Retry reduce
                PositionEvent.GOVERNANCE_KILL: PositionState.FLAT,
            },
            PositionState.CLOSED: {
                # Terminal state - no transitions
            }
        }
    
    def process_event(
        self, 
        position: PositionData, 
        event: PositionEvent, 
        event_data: Optional[Dict[str, Any]] = None
    ) -> TransitionResult:
        """Process an event and return transition result"""
        if event_data is None:
            event_data = {}
        
        current_state = position.state
        
        # Check if transition is allowed
        if current_state not in self._transitions:
            return TransitionResult(
                success=False,
                new_state=current_state,
                actions=[],
                reason=f"Invalid current state: {current_state}"
            )
        
        state_transitions = self._transitions[current_state]
        if event not in state_transitions:
            return TransitionResult(
                success=False,
                new_state=current_state,
                actions=[],
                reason=f"Event {event.value} not allowed in state {current_state.value}"
            )
        
        new_state = state_transitions[event]
        actions = self._get_actions_for_transition(current_state, new_state, event, event_data)
        
        # Update position
        position.state = new_state
        position.last_update_ts = int(time.time())
        
        # Set exit reason for terminal states
        if new_state == PositionState.CLOSED:
            position.exit_reason = event_data.get('reason', event.value)
        elif new_state == PositionState.FLAT and current_state != PositionState.FLAT:
            position.exit_reason = event_data.get('reason', f"force_close_{event.value}")
        
        return TransitionResult(
            success=True,
            new_state=new_state,
            actions=actions,
            reason=f"Transition: {current_state.value} → {new_state.value} on {event.value}",
            metadata={
                'event': event.value,
                'from_state': current_state.value,
                'to_state': new_state.value,
                'position_id': position.position_id
            }
        )
    
    def _get_actions_for_transition(
        self,
        from_state: PositionState,
        to_state: PositionState,
        event: PositionEvent,
        event_data: Dict[str, Any]
    ) -> List[str]:
        """Determine actions to take for a state transition"""
        actions = []
        
        # Emergency actions for risk/governance denials
        if event in [PositionEvent.RISK_DENY, PositionEvent.GOVERNANCE_KILL]:
            if to_state == PositionState.FLAT:
                actions.extend(["cancel_all_orders", "flatten_position", "log_emergency_exit"])
            elif to_state == PositionState.REDUCE_PENDING:
                actions.extend(["cancel_entry_orders", "reduce_to_zero", "log_risk_exit"])
        
        # Fill handling
        elif event in [PositionEvent.FILL_PARTIAL, PositionEvent.FILL_FULL]:
            fill_qty = event_data.get('fill_qty', 0)
            fill_price = event_data.get('fill_price', 0)
            
            if from_state == PositionState.ENTRY_PENDING and to_state == PositionState.OPEN:
                actions.extend([
                    "update_entry_price",
                    "start_reward_management",
                    "log_position_opened"
                ])
            elif from_state == PositionState.SCALE_IN_PENDING and to_state == PositionState.OPEN:
                actions.extend([
                    "update_position_size",
                    "reset_scale_cooldown",
                    "log_scale_in_complete"
                ])
            elif to_state == PositionState.CLOSED:
                actions.extend([
                    "update_final_pnl",
                    "cleanup_position",
                    "log_position_closed"
                ])
        
        # Order management
        elif from_state == PositionState.FLAT and to_state == PositionState.ENTRY_PENDING:
            actions.extend([
                "submit_entry_order",
                "set_position_ttl",
                "log_entry_attempt"
            ])
        
        elif from_state == PositionState.OPEN and to_state == PositionState.SCALE_IN_PENDING:
            actions.extend([
                "submit_scale_order",
                "set_scale_ttl",
                "log_scale_attempt"
            ])
        
        elif from_state == PositionState.OPEN and to_state == PositionState.REDUCE_PENDING:
            actions.extend([
                "submit_reduce_order",
                "set_reduce_ttl",
                "log_reduce_attempt"
            ])
        
        # TTL handling
        elif event == PositionEvent.TTL_EXPIRED:
            if to_state in [PositionState.REDUCE_PENDING, PositionState.FLAT]:
                actions.extend(["cancel_pending_orders", "force_close_position", "log_ttl_expired"])
        
        return actions
    
    def can_transition(self, position: PositionData, event: PositionEvent) -> bool:
        """Check if a transition is allowed from current state"""
        if position.state not in self._transitions:
            return False
        return event in self._transitions[position.state]
    
    def get_allowed_events(self, position: PositionData) -> List[PositionEvent]:
        """Get all events allowed from current state"""
        if position.state not in self._transitions:
            return []
        return list(self._transitions[position.state].keys())
    
    def is_terminal_state(self, state: PositionState) -> bool:
        """Check if a state is terminal (no outgoing transitions)"""
        return state not in self._transitions or not self._transitions[state]


__all__ = [
    "PositionState", "PositionEvent", "PositionData", 
    "TransitionResult", "PositionFSM"
]