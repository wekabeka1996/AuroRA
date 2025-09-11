"""
Integration tests for UnifiedExchangeAdapter idempotency behavior.
Covers HIT returning cached result, conflict detection, and dup metrics.
"""

from __future__ import annotations

import time

import pytest

from core.execution.exchange.common import (
    AbstractExchange,
    OrderRequest,
    OrderResult,
    OrderType,
    Side,
    SymbolInfo,
)
from core.execution.exchange.unified import (
    AdapterMode,
    ExchangeConfig,
    ExchangeType,
    UnifiedExchangeAdapter,
)
from core.execution.idem_guard import IdempotencyConflict, set_idem_metrics


class DummyExchange(AbstractExchange):
    def __init__(self):
        super().__init__(http=None)
        self.name = "dummy"
        self.calls = 0

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        return SymbolInfo(
            symbol=symbol,
            base="BTC",
            quote="USDT",
            tick_size=0.01,
            step_size=0.001,
            min_qty=0.001,
            min_notional=5.0,
        )

    def place_order(self, req: OrderRequest) -> OrderResult:
        self.calls += 1
        return OrderResult(
            order_id=f"ord_{int(time.time()*1000)}",
            client_order_id=req.client_order_id or "",
            status="ACK",
            executed_qty=0.0,
            cumm_quote_cost=0.0,
            fills=[],
            ts_ns=self.server_time_ns_hint(),
            raw={"dummy": True},
        )


class DummyAdapter(UnifiedExchangeAdapter):
    @property
    def exchange_name(self) -> str:
        return "dummy"

    def _create_exchange_instance(self) -> AbstractExchange:
        return DummyExchange()


def _make_adapter() -> DummyAdapter:
    cfg = ExchangeConfig(
        exchange_type=ExchangeType.BINANCE,  # value not used by dummy
        adapter_mode=AdapterMode.DEPENDENCY_FREE,
        api_key="",
        api_secret="",
        dry_run=True,
    )
    return DummyAdapter(cfg)


class _MetricsStub:
    def __init__(self):
        self.checks = {"hit": 0, "store": 0, "conflict": 0}
        self.dup = 0
        self.updates = {}

    def inc_check(self, kind: str) -> None:
        self.checks[kind] = self.checks.get(kind, 0) + 1

    def inc_dup_submit(self) -> None:
        self.dup += 1

    def inc_update(self, status: str) -> None:
        self.updates[status] = self.updates.get(status, 0) + 1


def test_hit_returns_cached_without_call(monkeypatch: pytest.MonkeyPatch):
    adapter = _make_adapter()
    ex = adapter._get_exchange()

    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        quantity=0.01,
        client_order_id="coid_hit_1",
    )

    _ = adapter.place_order_idempotent(req)
    assert ex.calls == 1

    r2 = adapter.place_order_idempotent(req)
    # No new call should be made on HIT
    assert ex.calls == 1
    # The cached result must match client_order_id and be OrderResult-like
    assert isinstance(r2, OrderResult)
    assert r2.client_order_id == req.client_order_id


def test_conflict_raises(monkeypatch: pytest.MonkeyPatch):
    adapter = _make_adapter()

    # Same client_order_id, different spec (price) should raise conflict on second submit
    req1 = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=0.01,
        price=50000.0,
        client_order_id="coid_conflict_1",
    )
    req2 = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=0.01,
        price=49000.0,  # different
        client_order_id="coid_conflict_1",
    )

    _ = adapter.place_order_idempotent(req1)
    with pytest.raises(IdempotencyConflict):
        adapter.place_order_idempotent(req2)


def test_dup_increments_metrics(monkeypatch: pytest.MonkeyPatch):
    metrics = _MetricsStub()
    set_idem_metrics(metrics)

    adapter = _make_adapter()

    req = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        quantity=0.02,
        client_order_id="coid_dup_metrics_1",
    )

    _ = adapter.place_order_idempotent(req)
    _ = adapter.place_order_idempotent(req)

    # We expect one store and one hit, and dup counter incremented
    assert metrics.checks.get("store", 0) >= 1
    assert metrics.checks.get("hit", 0) >= 1
    assert metrics.dup >= 1
