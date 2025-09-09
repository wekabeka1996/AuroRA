from decimal import getcontext, Decimal
import time
import pytest

# Адаптація під фактичну структуру
from core.execution.execution_service import ExecutionService
from core.execution.router_v2 import MarketSpec, OrderIntent
from core.aurora_event_logger import AuroraEventLogger

class SpyEventLogger(AuroraEventLogger):
    def __init__(self):
        super().__init__()
        self._events = []
    def emit(self, code: str, payload: dict | None = None, trace_id: str | None = None):
        self._events.append((code, payload or {}, trace_id))
        return super().emit(code, payload, trace_id)

@pytest.fixture(autouse=True)
def decimal_ctx():
    ctx = getcontext()
    ctx.prec = 28
    yield

@pytest.fixture
def event_logger():
    return SpyEventLogger()

@pytest.fixture
def market_spec_factory():
    def _mk(
        tick_size="0.10", lot_size="0.001", min_notional="10",
        maker_fee_bps=1, taker_fee_bps=5,
        best_bid="30000", best_ask="30000.5", spread_bps=Decimal('1.5')
    ):
        mid = (Decimal(best_bid) + Decimal(best_ask)) / Decimal('2')
        return MarketSpec(
            tick_size=Decimal(tick_size),
            lot_size=Decimal(lot_size),
            min_notional=Decimal(min_notional),
            maker_fee_bps=int(maker_fee_bps),
            taker_fee_bps=int(taker_fee_bps),
            best_bid=Decimal(best_bid),
            best_ask=Decimal(best_ask),
            spread_bps=float(spread_bps),
            mid=mid,
        )
    return _mk

@pytest.fixture
def intent_factory():
    def _mk(
        side="BUY",
        expected_return_bps=40,
        stop_dist_bps=80,
        tp_targets_bps=(120, 240),
        post_only=True,
        tif="GTC",
        working_type="mark",
        symbol="BTCUSDT",
        strategy_id="str-test",
        regime_state="trend",
        calib_ece=0.02,
        ts_ms=None,
        qty_hint="0.01"
    ):
        ts = int(time.time() * 1000) if ts_ms is None else ts_ms
        return OrderIntent(
            intent_id=f"intent-{ts}",
            timestamp_ms=ts,
            symbol=symbol,
            side=side,
            dir=1 if side == "BUY" else -1,
            strategy_id=strategy_id,
            expected_return_bps=int(expected_return_bps),
            stop_dist_bps=int(stop_dist_bps),
            tp_targets_bps=list(tp_targets_bps),
            risk_ctx={},
            regime_ctx={"governance": "shadow", "state": regime_state, "calib_ece": float(calib_ece)},
            exec_prefs={
                "post_only": bool(post_only),
                "tif": tif,
                "working_type": working_type,
            },
            qty_hint=Decimal(qty_hint)
        )
    return _mk

@pytest.fixture
def svc(event_logger):
    cfg = {
        'execution': {
            'router': {
                'p_min_fill': 0.25,
                'maker_spread_ok_bps': 2.5,
                'spread_deny_bps': 15,
                'switch_margin_bps': 0.2,
                'maker_offset_bps': 0.1,
                'percent_price_limit_bps': 7500,
            },
            'sla': {
                'kappa_bps_per_ms': 0.01,
                'edge_floor_bps': 0.0,
                'max_latency_ms': 500,
            }
        }
    }
    return ExecutionService(config=cfg, event_logger=event_logger)
