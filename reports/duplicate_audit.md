# Code Duplication Audit Report

Found a total of **394** duplication clusters from `jscpd` and `pylint`.

## Cluster 1: 92 lines (0 tokens) | Source: jscpd

Locations:
- `tests/fixtures/mock_exchange_factory.py` (Lines: 477-568)
- `tests/fixtures/mock_exchange_factory.py` (Lines: 183-274)

```python
,  # 0.1% fee
                fee_asset="USDT",
                ts_ns=int(time.time() * 1_000_000_000)
            )

            self.fills[order_id].append(fill)
            remaining_qty -= fill_qty

            # Simulate fill delay between partials
            if len(partial_ratios) > 1:
                await asyncio.sleep(0.05)

    async def _delayed_fill(self, order_id: str, order: OrderRequest):
        """Process delayed fills."""
        # Wait for configured delay
        delay = self.config.get("delay_ms", 100) / 1000
        await asyncio.sleep(delay)

        # Process fills if order still active
        if order_id in self.orders:
            await self._process_fills(order_id, order)


class MockExchangeFactory:
    """Factory for creating mock exchanges with different configurations."""

    @staticmethod
    def create_deterministic_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create deterministic exchange for predictable testing."""
        config = {
            "immediate": True,
            "latency_ms": 10,
            "partial": [1.0],  # Full fill by default
            "price_sequence": [],
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_stochastic_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create stochastic exchange with random behavior."""
        config = {
            "immediate": True,
            "latency_ms": random.randint(5, 50),
            "partial": MockExchangeFactory._generate_random_partial_ratios(),
            "price_variation": 0.02,  # 2% price variation
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_slow_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create slow exchange for testing timeouts."""
        config = {
            "immediate": False,
            "latency_ms": 200,
            "delay_ms": 500,
            "partial": [1.0],
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_partial_fill_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange that does partial fills."""
        config = {
            "immediate": True,
            "latency_ms": 20,
            "partial": [0.3, 0.4, 0.3],  # Multiple partial fills
            **(fill_profile or {})
        }
        return MockExchange(config)

    @staticmethod
    def create_rejecting_exchange(reject_rate: float = 0.1, fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange that randomly rejects orders."""
        config = {
            "immediate": True,
            "latency_ms": 15,
            "reject_rate": reject_rate,
            "partial": [1.0],
            **(fill_profile or {})
        }
        exchange = MockExchange(config)

        # Override submit_order to add rejection logic
        original_submit = exchange.submit_order
        async def rejecting_submit(order: OrderRequest) -> Dict[str, Any]:
            if random.random() < reject_rate:
                return {
                    "status": "rejected",
                    "order_id": f"mock_{order.client_order_id}"
```

---

## Cluster 2: 68 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 517-584)
- `tests/unit/test_shadow_broker.py` (Lines: 203-269)

```python
(self, mock_load_cfg, mock_get):
        """Test order validation with insufficient notional value."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        # Test insufficient notional (0.001 * 1.0 = 0.001 < 10.0)
        is_valid, message, qty, price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 0.001, 1.0
        )

        assert is_valid is False
        assert "MIN_NOTIONAL" in message

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_market_buy(self, mock_load_cfg, mock_get):
        """Test market buy order submission with slippage simulation."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"], slippage_bps=2.0)

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        result = broker.submit_order("BTCUSDT", "BUY", "MARKET", 1.0)

        assert result["status"] == "FILLED"
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["type"] == "MARKET"
        assert result["executedQty"] == "1.000"
        assert
```

---

## Cluster 3: 49 lines (0 tokens) | Source: jscpd

Locations:
- `tests/fixtures/mock_exchange_factory.py` (Lines: 568-616)
- `tests/fixtures/mock_exchange_factory.py` (Lines: 274-322)

```python
,
                    "reason": "RANDOM_REJECT",
                    "timestamp": time.time()
                }
            return await original_submit(order)

        exchange.submit_order = rejecting_submit
        return exchange

    @staticmethod
    def create_high_latency_exchange(fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange with high latency for performance testing."""
        config = {
            "immediate": True,
            "latency_ms": 500,  # 500ms latency
            "jitter_ms": 100,   # ±100ms jitter
            "partial": [1.0],
            **(fill_profile or {})
        }
        exchange = MockExchange(config)

        # Override to add jitter
        original_submit = exchange.submit_order
        async def jittery_submit(order: OrderRequest) -> Dict[str, Any]:
            result = await original_submit(order)
            # Add random jitter
            jitter = random.uniform(-config["jitter_ms"], config["jitter_ms"]) / 1000
            await asyncio.sleep(max(0, jitter))
            return result

        exchange.submit_order = jittery_submit
        return exchange

    @staticmethod
    def _generate_random_partial_ratios() -> List[float]:
        """Generate random partial fill ratios that sum to 1.0."""
        num_fills = random.randint(1, 4)
        ratios = [random.random() for _ in range(num_fills)]
        total = sum(ratios)
        return [r / total for r in ratios]

    @staticmethod
    def create_exchange_with_price_sequence(price_sequence: List[float],
                                          fill_profile: Optional[Dict[str, Any]] = None) -> MockExchange:
        """Create exchange with specific price sequence for testing."""
        config = {
            "immediate": True,
            "latency_ms": 10,
            "partial": [1.0
```

---

## Cluster 4: 47 lines (0 tokens) | Source: jscpd

Locations:
- `tests/fixtures/mock_exchange_factory.py` (Lines: 329-375)
- `tests/fixtures/mock_exchange_factory.py` (Lines: 34-80)

```python
class MockExchange:
    """Mock exchange implementation with configurable behavior."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.orders = {}  # order_id -> order
        self.fills = {}   # order_id -> list of fills
        self.reject_next = None
        self.price_sequence = config.get("price_sequence", [])
        self.price_index = 0

    def set_fill_profile(self, profile: Dict[str, Any]):
        """Update fill profile dynamically."""
        self.config.update(profile)

    def set_reject_next_order(self, reason: str):
        """Set next order to be rejected."""
        self.reject_next = reason

    def reset_reject_pattern(self):
        """Reset rejection pattern."""
        self.reject_next = None

    def trigger_partial_fill(self, order_id: str, quantity: Decimal, price: Decimal):
        """Manually trigger a partial fill for testing."""
        if order_id not in self.fills:
            self.fills[order_id] = []

        fill = Fill(
            price=float(price),
            qty=float(quantity),
            fee=float(quantity * price * Decimal("0.001")),  # 0.1% fee
            fee_asset="USDT",
            ts_ns=int(time.time() * 1_000_000_000)
        )

        self.fills[order_id].append(fill)

    async def submit_order(self, order: OrderRequest) -> Dict[str, Any]:
        """Submit order with configurable behavior."""
        # Check for rejection
        if self.reject_next:
            reason = self.reject_next
            self.reject_next = None
            return {
                "status": "rejected",
                "order_id": f"mock_{order.client_order_id}"
```

---

## Cluster 5: 45 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 399-443)
- `tests/unit/test_shadow_broker.py` (Lines: 85-129)

```python
(self, mock_load_cfg, mock_get):
        """Test getting filters for symbol."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {
            "symbols": [{
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.00001000",
                        "maxQty": "9000.00000000",
                        "stepSize": "0.00001000"
                    },
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "0.01000000",
                        "maxPrice": "1000000.00000000",
                        "tickSize": "0.01000000"
                    },
                    {
                        "filterType": "MIN_NOTIONAL",
                        "minNotional": "10.00000000"
                    }
                ]
            }]
        }
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])
        filters = broker.get_filters("BTCUSDT")

        assert filters is not None
        assert filters.lot_size_min_qty == Decimal("0.00001000")
        assert filters.lot_size_max_qty == Decimal("9000.00000000")
        assert filters.lot_size_step_size == Decimal("0.00001000")
        assert filters.min_notional == Decimal("10.00000000")

    @patch("core.execution.shadow_broker.load_binance_cfg"
```

---

## Cluster 6: 45 lines (0 tokens) | Source: jscpd

Locations:
- `tests/fixtures/mock_exchange_factory.py` (Lines: 382-426)
- `tests/fixtures/mock_exchange_factory.py` (Lines: 87-131)

```python
self.orders[order_id] = order

        # Simulate exchange processing delay
        latency = self.config.get("latency_ms", 10) / 1000
        await asyncio.sleep(latency)

        # Determine fill behavior
        if self.config.get("immediate", True):
            await self._process_fills(order_id, order)
        else:
            # Schedule fills asynchronously
            asyncio.create_task(self._delayed_fill(order_id, order))

        return {
            "status": "accepted",
            "order_id": order_id,
            "timestamp": time.time()
        }

    async def cancel_order(self, order_id: str) -> Dict[str, Any]:
        """Cancel order."""
        if order_id not in self.orders:
            return {"status": "not_found", "order_id": order_id}

        # Simulate cancellation delay
        latency = self.config.get("latency_ms", 10) / 1000
        await asyncio.sleep(latency)

        # Remove from active orders
        del self.orders[order_id]

        return {
            "status": "cancelled",
            "order_id": order_id,
            "timestamp": time.time()
        }

    async def get_order_status(self, order_id: str) -> Dict[str, Any]:
        """Get order status."""
        if order_id not in self.orders:
            return {"status": "not_found", "order_id": order_id}

        order = self.orders[order_id]
        fills = self.fills.get(order_id, [])
        filled_qty = sum(f.quantity
```

---

## Cluster 7: 41 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 621-661)
- `tests/unit/test_shadow_broker.py` (Lines: 307-347)

```python
assert float(result["fills"][0]["price"]) == 50000.0

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_validation_failure(self, mock_load_cfg, mock_get):
        """Test order rejection due to validation failure."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        # Submit order with invalid quantity
        result = broker.submit_order("BTCUSDT", "BUY", "LIMIT", 0.0005, 50000.0)

        # Fixed expected format for validation failure
        assert "code" in result
        assert result["code"] == -1013
        assert "Filter failure" in result["msg"]
        assert "LOT_SIZE" in result["msg"]


if __name__ == "__main__":
    unittest.main()
```

---

## Cluster 8: 38 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 584-621)
- `tests/unit/test_shadow_broker.py` (Lines: 270-306)

```python
assert "orderId" in result
        assert "fills" in result

    @patch("requests.get")
    @patch("core.execution.shadow_broker.load_binance_cfg")
    def test_submit_order_limit_order(self, mock_load_cfg, mock_get):
        """Test limit order submission at specified price."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        result = broker.submit_order("BTCUSDT", "BUY", "LIMIT", 1.0, 50000.0)

        assert result["status"] == "FILLED"
        assert result["symbol"] == "BTCUSDT"
        assert result["side"] == "BUY"
        assert result["type"] == "LIMIT"
        assert result["executedQty"] == "1.000"
        assert
```

---

## Cluster 9: 38 lines (0 tokens) | Source: jscpd

Locations:
- `tests/api/test_basic_endpoints.py` (Lines: 8-45)
- `tests/api/test_basic_endpoints_new.py` (Lines: 9-46)

```python
def make_client(tmp_path) -> TestClient:
    """Create test client with isolated environment"""
    os.environ['AURORA_API_TOKEN'] = 'test_token_12345678901234567890'
    os.environ['AURORA_IP_ALLOWLIST'] = '127.0.0.1'
    os.chdir(tmp_path)

    import api.service as svc
    importlib.reload(svc)
    return TestClient(svc.app)


def setup_app_state(client):
    """Setup minimal app state for testing"""
    app = client.app

    # Initialize basic state attributes
    if not hasattr(app.state, 'cfg'):
        app.state.cfg = {'test': 'config'}
    if not hasattr(app.state, 'trading_system'):
        app.state.trading_system = None
    if not hasattr(app.state, 'governance'):
        from aurora.governance import Governance
        app.state.governance = Governance()
    if not hasattr(app.state, 'events_emitter'):
        app.state.events_emitter = MagicMock()
    if not hasattr(app.state, 'last_event_ts'):
        app.state.last_event_ts = None
    if not hasattr(app.state, 'session_dir'):
        from pathlib import Path
        app.state.session_dir = Path('logs')

    return app


class TestBasicEndpoints:
    """Test basic API endpoints that don't require complex setup"""

    def test_root_endpoint_redirects_to_docs
```

---

## Cluster 10: 37 lines (0 tokens) | Source: jscpd

Locations:
- `core/execution/router_backup.py` (Lines: 361-397)
- `core/execution/router_backup.py` (Lines: 309-345)

```python
,
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=maker_net,
                net_e_taker_bps=taker_net,
                scores={"expected_maker_bps": exp_maker, "taker_bps": taker_net, "p_fill": p_fill},
            )

        # Standard decision logic: choose route with higher expected edge
        if taker_net >= exp_maker and taker_net > 0.0:
            return RouteDecision(
                route="taker",
                e_maker_bps=e_maker,
                e_taker_bps=e_taker,
                p_fill=p_fill,
                reason=f"E_taker {taker_net:.2f} ≥ E_maker {exp_maker:.2f}; SLA OK",
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=maker_net,
                net_e_taker_bps=taker_net,
                scores={"expected_maker_bps": exp_maker, "taker_bps": taker_net, "p_fill": p_fill}
            )
        if exp_maker > taker_net and exp_maker > 0.0 and p_fill >= self._min_p:
            return RouteDecision(
                route="maker",
                e_maker_bps=e_maker,
                e_taker_bps=e_taker,
                p_fill=p_fill,
                reason=f"E_maker {exp_maker:.2f} > E_taker {taker_net:.2f}; Pfill {p_fill:.2f} ≥ {self._min_p:.2f}",
                maker_fee_bps=self._fees.maker_fee_bps,
                taker_fee_bps=self._fees.taker_fee_bps,
                net_e_maker_bps=maker_net,
                net_e_taker_bps=taker_net,
                scores={"expected_maker_bps": exp_maker, "taker_bps": taker_net, "p_fill": p_fill}
            )

        # None attractive - use correct net edges in the denial message
```

---

## Cluster 11: 35 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 445-479)
- `tests/unit/test_shadow_broker.py` (Lines: 131-165)

```python
(self, mock_load_cfg, mock_get):
        """Test successful order validation and rounding."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.00001"),
            lot_size_max_qty=Decimal("9000"),
            lot_size_step_size=Decimal("0.00001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("1000000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        is_valid, message, qty, price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 1.0, 50000.0
        )

        assert is_valid is True
        assert message == "OK"
        assert qty == 1.0
        assert price == 50000.0

    @patch("core.execution.shadow_broker.load_binance_cfg"
```

---

## Cluster 12: 35 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 481-515)
- `tests/unit/test_shadow_broker.py` (Lines: 167-201)

```python
(self, mock_load_cfg, mock_get):
        """Test order validation with invalid quantity."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        # Test quantity too small
        is_valid, message, qty, price = broker.validate_and_round_order(
            "BTCUSDT", "BUY", "LIMIT", 0.0005, 50000.0
        )

        assert is_valid is False
        assert "LOT_SIZE" in message
        assert "Quantity" in message

    @patch("core.execution.shadow_broker.load_binance_cfg"
```

---

## Cluster 13: 33 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/api/test_api_survived_mutants.py` (Lines: 240-272)
- `tests/unit/core_aurora/test_core_aurora_survived_mutants.py` (Lines: 297-329)

```python
:
    """Targeted tests for dictionary access pattern mutants"""

    def test_get_or_default_patterns_mutant(self):
        """Kill mutant: 'or' -> 'and' in dict.get() or default patterns"""

        test_dicts = [
            {},  # Empty dict
            {"key": "value"},  # Has key
            {"other_key": "value"},  # Missing key
        ]

        for d in test_dicts:
            # Test pattern: d.get('key') or default
            result = d.get('key') or "default"
            assert result is not None

            # Test pattern: d.get('key') or {}
            result_dict = d.get('key') or {}
            assert isinstance(result_dict, (str, dict))

    def test_compound_get_or_patterns_mutant(self):
        """Kill mutant: boolean logic in compound get() or patterns"""

        test_dicts = [
            {},  # Missing both
            {"guards": {}},  # Has guards
            {"gates": {}},   # Has gates
            {"guards": {}, "gates": {}},  # Has both
        ]

        for d in test_dicts:
            # Test pattern: ((d.get('guards') or d.get('gates') or {}))
```

---

## Cluster 14: 32 lines (0 tokens) | Source: jscpd

Locations:
- `tests/test_signal.py` (Lines: 68-99)
- `tools/mutation_test_standalone.py` (Lines: 63-94)

```python
):
        """Test adding tick data"""
        calculator = CrossAssetHY()
        calculator.add_tick("SOL", 1000.0, 50.0)
        # Should not raise exception
        assert True


# Simple comparison tests for mutation testing
def test_simple_comparisons():
    """Simple tests that mutation testing can work with"""
    x = 5
    y = 10

    # These comparisons will be mutated by our simple mutator
    assert x < y
    assert x != y
    assert y > x
    assert x <= 5
    assert y >= 10


def test_boolean_logic():
    """Boolean logic tests for mutation testing"""
    a = True
    b = False

    # These will be mutated (and/or operations)
    assert a and not b
    assert a or b
    assert not (a and b)
    assert (a or b) and True
```

---

## Cluster 15: 28 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 94-121)
- `tests/unit/test_shadow_broker_old.py` (Lines: 412-440)

```python
mock_response.json.return_value = {
            "symbols": [{
                "symbol": "BTCUSDT",
                "status": "TRADING",
                "filters": [
                    {
                        "filterType": "LOT_SIZE",
                        "minQty": "0.00001000",
                        "maxQty": "9000.00000000",
                        "stepSize": "0.00001000"
                    },
                    {
                        "filterType": "PRICE_FILTER",
                        "minPrice": "0.01000000",
                        "maxPrice": "1000000.00000000",
                        "tickSize": "0.01000000"
                    },
                    {
                        "filterType": "MIN_NOTIONAL",
                        "minNotional": "10.00000000"
                    }
                ]
            }]
        }
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])
        filters
```

---

## Cluster 16: 28 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_idempotency_store_basic.py` (Lines: 29-56)
- `tests/unit/test_idempotency_store_basic.py` (Lines: 1-28)

```python
from core.infra.idempotency_store import IdempotencyStore


def test_put_get_seen_and_sweep():
    # deterministic now_ns for testing
    now_ns = lambda: 1_000_000_000
    store = IdempotencyStore(ttl_sec=3600, now_ns_fn=now_ns)
    key = "op-123"
    assert not store.seen(key)
    store.put(key, {"ok": True})
    assert store.seen(key)
    assert store.get(key) == {"ok": True}
    # sweep should remove nothing for large ttl
    removed = store.sweep()
    assert removed == 0


def test_sweep_removes_expired():
    t = [1_000_000_000]
    now_ns = lambda: t[0]
    store = IdempotencyStore(ttl_sec=0.000001, now_ns_fn=now_ns)  # tiny ttl
    store.put("k", 1)
    assert store.seen("k")
    # advance time beyond ttl
    t[0] += int(1e9)
    removed = store.sweep()
    assert removed == 1
    assert not store.seen("k")
```

---

## Cluster 17: 27 lines (0 tokens) | Source: jscpd

Locations:
- `core/execution/router_backup.py` (Lines: 247-273)
- `core/execution/router_backup.py` (Lines: 215-241)

```python
if e_maker > 0.0 and p_fill >= self._min_p:
                return RouteDecision(
                    route="maker",
                    e_maker_bps=e_maker,
                    e_taker_bps=e_taker,
                    p_fill=p_fill,
                    reason=f"SLA denied taker, fallback to maker (E_maker={e_maker:.2f}bps, Pfill={p_fill:.2f})",
                    maker_fee_bps=self._fees.maker_fee_bps,
                    taker_fee_bps=self._fees.taker_fee_bps,
                    net_e_maker_bps=e_maker,
                    net_e_taker_bps=e_taker,
                    scores={"expected_maker_bps": e_maker, "taker_bps": e_taker, "p_fill": p_fill}
                )

            # Special-case: if P(fill) is very low (below taker threshold) but taker
            # edge is positive, prefer taker despite SLA edge floor. Tests rely on
            # this behaviour for low-P scenarios.
            if p_fill < p_taker_threshold and e_taker > 0.0:
                return RouteDecision(
                    route="taker",
                    e_maker_bps=e_maker,
                    e_taker_bps=e_taker,
                    p_fill=p_fill,
                    reason=f"Low Pfill {p_fill:.2f} < {p_taker_threshold:.2f}; override SLA and prefer taker (E_taker={e_taker:.2f})",
                    maker_fee_bps=self._fees.maker_fee_bps,
                    taker_fee_bps=self._fees.taker_fee_bps,
                    net_e_maker_bps=e_taker
```

---

## Cluster 18: 24 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 205-228)
- `tests/unit/test_shadow_broker.py` (Lines: 133-58)

```python
mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        # Test insufficient notional (0.001 * 1.0 = 0.001 < 10.0)
```

---

## Cluster 19: 24 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 277-300)
- `tests/unit/test_shadow_broker.py` (Lines: 133-263)

```python
mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        result = broker.submit_order("BTCUSDT", "BUY", "LIMIT"
```

---

## Cluster 20: 24 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 313-336)
- `tests/unit/test_shadow_broker.py` (Lines: 133-58)

```python
mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        # Set up test filters manually
        broker.filters["BTCUSDT"] = BinanceFilters(
            lot_size_min_qty=Decimal("0.001"),
            lot_size_max_qty=Decimal("1000"),
            lot_size_step_size=Decimal("0.001"),
            price_filter_min_price=Decimal("0.01"),
            price_filter_max_price=Decimal("100000"),
            price_filter_tick_size=Decimal("0.01"),
            min_notional=Decimal("10.0")
        )

        # Submit order with invalid quantity
```

---

## Cluster 21: 24 lines (0 tokens) | Source: jscpd

Locations:
- `tests/integration/test_governance_gate.py` (Lines: 318-341)
- `tests/integration/test_governance_gate.py` (Lines: 140-163)

```python
events_logged = []

        def mock_log_events(code: str, details: dict):
            events_logged.append({"code": code, "details": details})

        with patch("skalp_bot.runner.run_live_aurora._log_events", side_effect=mock_log_events):
            with patch.dict(os.environ, {
                "DRY_RUN": "true",
                "AURORA_MAX_TICKS": "2"
            }):
                with patch("skalp_bot.runner.run_live_aurora.create_adapter") as mock_adapter_factory:
                    mock_adapter = MockAdapter(MockMarketData())
                    mock_adapter_factory.return_value = mock_adapter

                    with patch("yaml.safe_load", return_value=self.test_config):
                        with patch("pathlib.Path.exists", return_value=True):
                            with patch("pathlib.Path.read_text", return_value=""):
                                try:
                                    from skalp_bot.runner.run_live_aurora import main
                                    main(config_path="test_config.yaml")
                                except SystemExit:
                                    pass

        # Find governance events
```

---

## Cluster 22: 24 lines (0 tokens) | Source: jscpd

Locations:
- `tests/api/test_basic_endpoints.py` (Lines: 57-80)
- `tests/api/test_basic_endpoints_new.py` (Lines: 56-78)

```python
)
        response = client.get('/version')
        assert response.status_code == 200
        data = response.json()
        assert 'version' in data
        assert isinstance(data['version'], str)

    def test_health_endpoint_with_models_loaded(self, tmp_path):
        """Test health endpoint when models are loaded"""
        client = make_client(tmp_path)
        setup_app_state(client)

        # Mock trading system as loaded
        with patch.object(client.app.state, 'trading_system') as mock_ts:
            mock_ts.student = MagicMock()
            mock_ts.router = MagicMock()

            response = client.get('/health')
            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'healthy'
            assert data['models_loaded'] is True

    def
```

---

## Cluster 23: 23 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_tca_identity.py` (Lines: 87-109)
- `tests/unit/test_tca_identity.py` (Lines: 35-57)

```python
components_sum = (
        metrics.raw_edge_bps +
        metrics.fees_bps +
        metrics.spread_cost_bps +
        metrics.latency_slippage_bps +
        metrics.adverse_selection_bps +
        metrics.temporary_impact_bps +
        metrics.rebate_bps
    )

    assert abs(metrics.implementation_shortfall_bps - components_sum) <= 1e-6

    # Check sign conventions
    assert metrics.fees_bps <= 0
    assert metrics.slippage_in_bps <= 0  # Maker profile -> 0
    assert metrics.slippage_out_bps <= 0
    assert metrics.adverse_bps <= 0
    assert metrics.latency_bps <= 0
    assert metrics.impact_bps <= 0
    assert metrics.rebate_bps >= 0


def test_maker_profile_with_rebate
```

---

## Cluster 24: 23 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker.py` (Lines: 354-376)
- `tests/unit/test_shadow_broker.py` (Lines: 40-62)

```python
)
    def test_shadow_broker_initialization(self, mock_load_cfg, mock_get):
        """Test ShadowBroker initialization with proper config loading."""
        mock_cfg = Mock()
        mock_cfg.base_url = "https://api.binance.com"
        mock_cfg.api_key = "test_key"
        mock_cfg.api_secret = "test_secret"
        mock_load_cfg.return_value = mock_cfg

        # Mock exchange info response
        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"symbols": []}
        mock_get.return_value = mock_response

        broker = ShadowBroker(symbols=["BTCUSDT"])

        assert "BTCUSDT" in broker.symbols
        assert broker.slippage_bps == 2.0
        mock_load_cfg.assert_called_once()

    @patch("requests.get")
    @patch('core.execution.shadow_broker.load_binance_cfg'
```

---

## Cluster 25: 23 lines (0 tokens) | Source: jscpd

Locations:
- `tools/simple_mutator.py` (Lines: 209-231)
- `tools/ultra_simple_mutator.py` (Lines: 317-339)

```python
# Calculate results
        mutation_score = (self.mutants_killed / self.mutants_created * 100) if self.mutants_created > 0 else 0

        results = {
            "total_files": len(python_files),
            "total_mutants": self.mutants_created,
            "killed_mutants": self.mutants_killed,
            "survived_mutants": self.mutants_survived,
            "mutation_score": round(mutation_score, 2),
            "timestamp": time.time()
        }

        print("\n📊 Mutation Testing Results:")
        print(f"   Total mutants: {results['total_mutants']}")
        print(f"   Killed: {results['killed_mutants']}")
        print(f"   Survived: {results['survived_mutants']}")
        print(f"   Mutation score: {results['mutation_score']}%")

        return results

def main():
    if len(sys.argv) < 3:
        print("Usage: python simple_mutator.py <source_dir> <test_command>"
```

---

## Cluster 26: 22 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker_old.py` (Lines: 83-104)
- `tests/unit/test_shadow_broker_old.py` (Lines: 39-60)

```python
@patch('core.env_config.load_binance_cfg')
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0")
                )
            }

            # Quantity below minimum
```

---

## Cluster 27: 22 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker_old.py` (Lines: 115-136)
- `tests/unit/test_shadow_broker_old.py` (Lines: 39-60)

```python
@patch('core.env_config.load_binance_cfg')
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0")
                )
            }

            # Quantity above maximum
```

---

## Cluster 28: 22 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker_old.py` (Lines: 221-242)
- `tests/unit/test_shadow_broker_old.py` (Lines: 39-60)

```python
@patch('core.env_config.load_binance_cfg')
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0")
                )
            }

            # Price below minimum
```

---

## Cluster 29: 22 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker_old.py` (Lines: 253-274)
- `tests/unit/test_shadow_broker_old.py` (Lines: 39-60)

```python
@patch('core.env_config.load_binance_cfg')
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0")
                )
            }

            # Price above maximum
```

---

## Cluster 30: 22 lines (0 tokens) | Source: jscpd

Locations:
- `tests/unit/test_shadow_broker_old.py` (Lines: 316-337)
- `tests/unit/test_shadow_broker_old.py` (Lines: 39-60)

```python
@patch('core.env_config.load_binance_cfg')
        def test_inner(mock_load_cfg):
            mock_cfg = Mock()
            mock_cfg.base_url = "https://api.binance.com"
            mock_load_cfg.return_value = mock_cfg

            broker = ShadowBroker(symbols=["BTCUSDT"])

            # Mock filters
            broker.filters = {
                "BTCUSDT": BinanceFilters(
                    lot_size_min_qty=Decimal("0.001"),
                    lot_size_max_qty=Decimal("1000"),
                    lot_size_step_size=Decimal("0.001"),
                    price_filter_min_price=Decimal("0.01"),
                    price_filter_max_price=Decimal("100000"),
                    price_filter_tick_size=Decimal("0.01"),
                    min_notional=Decimal("10.0")
                )
            }

            # Valid notional (1.0 * 15.0 = 15.0 > 10.0)
```

---
