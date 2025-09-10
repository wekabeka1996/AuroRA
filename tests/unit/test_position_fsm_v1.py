from __future__ import annotations

import pytest

from core.position_fsm import PositionData, PositionEvent, PositionFSM, PositionState


class TestPositionFSM:
    """Unit tests for PositionFSM v1.0"""

    @pytest.fixture
    def fsm(self) -> PositionFSM:
        """Test FSM instance"""
        return PositionFSM()

    @pytest.fixture
    def initial_position(self) -> PositionData:
        """Initial position in FLAT state"""
        return PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            state=PositionState.FLAT
        )

    def test_initialization(self, fsm: PositionFSM):
        """Test FSM initialization"""
        assert fsm._transitions is not None
        assert PositionState.FLAT in fsm._transitions
        assert PositionState.ENTRY_PENDING in fsm._transitions
        assert PositionState.OPEN in fsm._transitions
        assert PositionState.CLOSED in fsm._transitions

    def test_flat_to_entry_pending_transition(self, fsm: PositionFSM, initial_position: PositionData):
        """Test FLAT → ENTRY_PENDING transition"""
        result = fsm.process_event(initial_position, PositionEvent.EDGE_CHANGE)

        assert result.success == True
        assert result.new_state == PositionState.ENTRY_PENDING
        assert initial_position.state == PositionState.ENTRY_PENDING
        assert "submit_entry_order" in result.actions
        assert "set_position_ttl" in result.actions

    def test_entry_pending_to_open_transition(self, fsm: PositionFSM):
        """Test ENTRY_PENDING → OPEN transition"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            state=PositionState.ENTRY_PENDING
        )

        result = fsm.process_event(position, PositionEvent.FILL_FULL)

        assert result.success == True
        assert result.new_state == PositionState.OPEN
        assert position.state == PositionState.OPEN
        assert "update_entry_price" in result.actions
        assert "start_reward_management" in result.actions

    def test_open_to_reduce_pending_tp_hit(self, fsm: PositionFSM):
        """Test OPEN → REDUCE_PENDING on TP hit"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        result = fsm.process_event(position, PositionEvent.TP_HIT)

        assert result.success == True
        assert result.new_state == PositionState.REDUCE_PENDING
        assert position.state == PositionState.REDUCE_PENDING
        assert "submit_reduce_order" in result.actions
        assert "set_reduce_ttl" in result.actions

    def test_open_to_scale_in_pending(self, fsm: PositionFSM):
        """Test OPEN → SCALE_IN_PENDING transition"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        result = fsm.process_event(position, PositionEvent.SCALE_SIGNAL)

        assert result.success == True
        assert result.new_state == PositionState.SCALE_IN_PENDING
        assert position.state == PositionState.SCALE_IN_PENDING
        assert "submit_scale_order" in result.actions
        assert "set_scale_ttl" in result.actions

    def test_scale_in_pending_to_open_on_fill(self, fsm: PositionFSM):
        """Test SCALE_IN_PENDING → OPEN on successful fill"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.SCALE_IN_PENDING
        )

        result = fsm.process_event(position, PositionEvent.FILL_FULL)

        assert result.success == True
        assert result.new_state == PositionState.OPEN
        assert position.state == PositionState.OPEN
        assert "update_position_size" in result.actions
        assert "reset_scale_cooldown" in result.actions

    def test_reduce_pending_to_closed_on_fill(self, fsm: PositionFSM):
        """Test REDUCE_PENDING → CLOSED on successful fill"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.REDUCE_PENDING
        )

        result = fsm.process_event(position, PositionEvent.FILL_FULL)

        assert result.success == True
        assert result.new_state == PositionState.CLOSED
        assert position.state == PositionState.CLOSED
        assert position.exit_reason == PositionEvent.FILL_FULL.value
        assert "update_final_pnl" in result.actions
        assert "cleanup_position" in result.actions

    def test_risk_deny_from_entry_pending(self, fsm: PositionFSM):
        """Test RISK_DENY from ENTRY_PENDING flattens position"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            state=PositionState.ENTRY_PENDING
        )

        result = fsm.process_event(position, PositionEvent.RISK_DENY)

        assert result.success == True
        assert result.new_state == PositionState.FLAT
        assert position.state == PositionState.FLAT
        assert position.exit_reason == f"force_close_{PositionEvent.RISK_DENY.value}"
        assert "cancel_all_orders" in result.actions
        assert "flatten_position" in result.actions

    def test_governance_kill_from_open(self, fsm: PositionFSM):
        """Test GOVERNANCE_KILL from OPEN triggers emergency reduce"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        result = fsm.process_event(position, PositionEvent.GOVERNANCE_KILL)

        assert result.success == True
        assert result.new_state == PositionState.REDUCE_PENDING
        assert position.state == PositionState.REDUCE_PENDING
        assert "cancel_entry_orders" in result.actions
        assert "reduce_to_zero" in result.actions

    def test_ttl_expired_from_open(self, fsm: PositionFSM):
        """Test TTL_EXPIRED from OPEN triggers reduce"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        result = fsm.process_event(position, PositionEvent.TTL_EXPIRED)

        assert result.success == True
        assert result.new_state == PositionState.REDUCE_PENDING
        assert position.state == PositionState.REDUCE_PENDING
        assert "submit_reduce_order" in result.actions
        assert "set_reduce_ttl" in result.actions
        assert "log_reduce_attempt" in result.actions

    def test_exchange_reject_handling(self, fsm: PositionFSM):
        """Test EXCHANGE_REJECT handling in various states"""
        # From ENTRY_PENDING
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            state=PositionState.ENTRY_PENDING
        )

        result = fsm.process_event(position, PositionEvent.EXCHANGE_REJECT)

        assert result.success == True
        assert result.new_state == PositionState.FLAT
        # EXCHANGE_REJECT transition doesn't have specific actions defined
        assert result.actions == []

    def test_partial_fill_transitions(self, fsm: PositionFSM):
        """Test partial fill handling"""
        # ENTRY_PENDING with partial fill stays in ENTRY_PENDING
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            state=PositionState.ENTRY_PENDING
        )

        result = fsm.process_event(position, PositionEvent.FILL_PARTIAL)

        assert result.success == True
        assert result.new_state == PositionState.ENTRY_PENDING
        assert position.state == PositionState.ENTRY_PENDING

    def test_invalid_transition(self, fsm: PositionFSM, initial_position: PositionData):
        """Test invalid state transition"""
        # Try to go from FLAT to OPEN directly (invalid)
        result = fsm.process_event(initial_position, PositionEvent.FILL_FULL)

        assert result.success == False
        assert result.new_state == PositionState.FLAT
        assert "not allowed" in result.reason

    def test_terminal_state_transitions(self, fsm: PositionFSM):
        """Test that CLOSED state has no outgoing transitions"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            state=PositionState.CLOSED
        )

        # Any event from CLOSED should fail
        result = fsm.process_event(position, PositionEvent.EDGE_CHANGE)

        assert result.success == False
        assert result.new_state == PositionState.CLOSED
        assert "not allowed" in result.reason

    def test_can_transition_method(self, fsm: PositionFSM, initial_position: PositionData):
        """Test can_transition method"""
        # FLAT can transition to ENTRY_PENDING
        assert fsm.can_transition(initial_position, PositionEvent.EDGE_CHANGE) == True

        # FLAT cannot transition to OPEN
        assert fsm.can_transition(initial_position, PositionEvent.FILL_FULL) == False

    def test_get_allowed_events(self, fsm: PositionFSM, initial_position: PositionData):
        """Test get_allowed_events method"""
        allowed_events = fsm.get_allowed_events(initial_position)

        assert PositionEvent.EDGE_CHANGE in allowed_events
        assert PositionEvent.FILL_FULL not in allowed_events

    def test_is_terminal_state(self, fsm: PositionFSM):
        """Test is_terminal_state method"""
        assert fsm.is_terminal_state(PositionState.CLOSED) == True
        assert fsm.is_terminal_state(PositionState.FLAT) == False
        assert fsm.is_terminal_state(PositionState.OPEN) == False

    def test_transition_with_event_data(self, fsm: PositionFSM):
        """Test transition with event data"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        event_data = {
            'reduce_qty': 0.5,
            'reason': 'tp_hit_level_1'
        }

        result = fsm.process_event(position, PositionEvent.TP_HIT, event_data)

        assert result.success == True
        assert result.new_state == PositionState.REDUCE_PENDING
        assert result.metadata is not None
        assert result.metadata['event'] == 'tp_hit'
        assert result.metadata['from_state'] == 'OPEN'
        assert result.metadata['to_state'] == 'REDUCE_PENDING'

    def test_trail_hit_transition(self, fsm: PositionFSM):
        """Test TRAIL_HIT transition"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        result = fsm.process_event(position, PositionEvent.TRAIL_HIT)

        assert result.success == True
        assert result.new_state == PositionState.REDUCE_PENDING
        assert "submit_reduce_order" in result.actions

    def test_reduce_signal_transition(self, fsm: PositionFSM):
        """Test REDUCE_SIGNAL transition"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.OPEN
        )

        result = fsm.process_event(position, PositionEvent.REDUCE_SIGNAL)

        assert result.success == True
        assert result.new_state == PositionState.REDUCE_PENDING
        assert "submit_reduce_order" in result.actions

    def test_scale_in_pending_risk_deny(self, fsm: PositionFSM):
        """Test RISK_DENY from SCALE_IN_PENDING reverts to OPEN"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.SCALE_IN_PENDING
        )

        result = fsm.process_event(position, PositionEvent.RISK_DENY)

        assert result.success == True
        assert result.new_state == PositionState.OPEN
        assert position.state == PositionState.OPEN
        # RISK_DENY from SCALE_IN_PENDING doesn't have specific actions defined
        assert result.actions == []

    def test_scale_in_pending_ttl_expired(self, fsm: PositionFSM):
        """Test TTL_EXPIRED from SCALE_IN_PENDING reverts to OPEN"""
        position = PositionData(
            position_id="test_pos_1",
            symbol="BTCUSDT",
            side="BUY",
            target_qty=1.0,
            current_qty=1.0,
            state=PositionState.SCALE_IN_PENDING
        )

        result = fsm.process_event(position, PositionEvent.TTL_EXPIRED)

        assert result.success == True
        assert result.new_state == PositionState.OPEN
        assert position.state == PositionState.OPEN
