"""
Unified Exchange Adapter Tests
==============================

Comprehensive tests for the unified exchange adapter interface:
- Factory pattern testing
- Configuration management
- Error handling and logging
- Fee integration
- Multi-exchange support
"""

from pathlib import Path
import tempfile

import pytest

from core.execution.exchange.common import (
    ExchangeError,
    Fees,
    OrderRequest,
    OrderType,
    Side,
    ValidationError,
)
from core.execution.exchange.config import (
    ExchangeConfig as ConfigConfig,
    ExchangeConfigManager,
)
from core.execution.exchange.error_handling import (
    CircuitBreakerConfig,
    ErrorCategory,
    ErrorSeverity,
    ExchangeCircuitBreaker,
    ExchangeErrorContext,
    ExchangeErrorHandler,
    ExchangeRetryHandler,
    RetryConfig,
)
from core.execution.exchange.unified import (
    AdapterMode,
    BinanceAdapter,
    CCXTBinanceAdapter,
    ExchangeAdapterFactory,
    ExchangeConfig,
    ExchangeType,
    GateAdapter,
    create_exchange_adapter,
)


class MockHttpClient:
    """Mock HTTP client for testing."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.requests = []

    def request(self, method, url, *, params=None, headers=None, json=None):
        self.requests.append((method, url, params, headers, json))
        # Return mock response based on URL pattern
        for pattern, response in self.responses.items():
            if pattern in url:
                return response
        return {}


# Test Factory Pattern
def test_exchange_adapter_factory():
    """Test exchange adapter factory creation."""
    config = ExchangeConfig(
        exchange_type=ExchangeType.BINANCE,
        adapter_mode=AdapterMode.DEPENDENCY_FREE,
        api_key="test_key",
        api_secret="test_secret",
        dry_run=True
    )

    adapter = ExchangeAdapterFactory.create_adapter(config)
    assert isinstance(adapter, BinanceAdapter)
    assert adapter.exchange_name == "binance"
    assert adapter.is_dry_run() is True


def test_factory_with_all_exchange_types():
    """Test factory with all supported exchange types."""
    test_configs = [
        (ExchangeType.BINANCE, BinanceAdapter),
        (ExchangeType.GATE, GateAdapter),
        (ExchangeType.BINANCE_CCXT, CCXTBinanceAdapter),
    ]

    for exchange_type, expected_class in test_configs:
        config = ExchangeConfig(
            exchange_type=exchange_type,
            adapter_mode=AdapterMode.DEPENDENCY_FREE,
            api_key="test",
            api_secret="test",
            dry_run=True
        )

        adapter = ExchangeAdapterFactory.create_adapter(config)
        assert isinstance(adapter, expected_class)
        assert adapter.exchange_name == exchange_type.value


def test_convenience_function():
    """Test convenience function for adapter creation."""
    adapter = create_exchange_adapter(
        "binance",
        api_key="test",
        api_secret="test",
        dry_run=True
    )

    assert isinstance(adapter, BinanceAdapter)
    assert adapter.exchange_name == "binance"


def test_supported_exchanges():
    """Test listing supported exchanges."""
    supported = ExchangeAdapterFactory.get_supported_exchanges()
    expected = ["binance", "gate", "binance_ccxt"]

    for exchange in expected:
        assert exchange in supported


# Test Configuration Management
def test_exchange_config_creation():
    """Test exchange configuration creation."""
    config = ConfigConfig.create(
        name="test_exchange",
        exchange_type=ExchangeType.BINANCE,
        api_key="test_key",
        api_secret="test_secret",
        dry_run=True,
        testnet=True
    )

    assert config.name == "test_exchange"
    assert config.settings.type == ExchangeType.BINANCE
    assert config.credentials.api_key == "test_key"
    assert config.settings.dry_run is True
    assert config.is_valid() is True


def test_config_validation():
    """Test configuration validation."""
    # Valid config
    valid_config = ConfigConfig.create(
        name="valid",
        exchange_type=ExchangeType.BINANCE,
        api_key="key",
        api_secret="secret",
        dry_run=True
    )
    assert valid_config.is_valid() is True

    # Invalid config - missing name
    invalid_config = ConfigConfig.create(
        name="",
        exchange_type=ExchangeType.BINANCE,
        api_key="key",
        api_secret="secret"
    )
    assert invalid_config.is_valid() is False


def test_config_manager():
    """Test configuration manager operations."""
    with tempfile.TemporaryDirectory() as temp_dir:
        manager = ExchangeConfigManager(Path(temp_dir))

        # Create config
        config = manager.create_config(
            "test_exchange",
            ExchangeType.BINANCE,
            api_key="test",
            api_secret="test"
        )

        # Retrieve config
        retrieved = manager.get_config("test_exchange")
        assert retrieved is not None
        assert retrieved.name == "test_exchange"

        # List configs
        configs = manager.list_configs()
        assert "test_exchange" in configs

        # Update config
        updated = manager.update_config("test_exchange", dry_run=False)
        assert updated is not None
        assert updated.settings.dry_run is False

        # Delete config
        assert manager.delete_config("test_exchange") is True
        assert manager.get_config("test_exchange") is None


# Test Error Handling
def test_error_classification():
    """Test error classification and handling."""
    handler = ExchangeErrorHandler()
    context = ExchangeErrorContext(
        exchange_name="binance",
        operation="place_order",
        symbol="BTCUSDT"
    )

    # Test network error
    network_error = ConnectionError("Connection failed")
    error_info = handler.classify_error(network_error, context)

    assert error_info.category == ErrorCategory.NETWORK
    assert error_info.severity == ErrorSeverity.HIGH
    assert error_info.retryable is True

    # Test validation error
    validation_error = ValidationError("Invalid order")
    error_info = handler.classify_error(validation_error, context)

    assert error_info.category == ErrorCategory.VALIDATION
    assert error_info.severity == ErrorSeverity.LOW
    assert error_info.retryable is False


def test_retry_handler():
    """Test retry handler with exponential backoff."""
    config = RetryConfig(max_attempts=3, base_delay=0.1)
    retry_handler = ExchangeRetryHandler(config)
    error_handler = ExchangeErrorHandler()
    context = ExchangeErrorContext("binance", "test_operation")

    call_count = 0

    def failing_operation():
        nonlocal call_count
        call_count += 1
        if call_count < 3:
            raise ConnectionError("Temporary failure")
        return "success"

    result = retry_handler.execute_with_retry(
        failing_operation,
        error_handler,
        context
    )

    assert result == "success"
    assert call_count == 3


def test_circuit_breaker():
    """Test circuit breaker functionality."""
    config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=0.1)
    breaker = ExchangeCircuitBreaker(config)

    # Initial state
    assert breaker.state.name == "CLOSED"

    # Cause failures
    with pytest.raises(ZeroDivisionError):
        breaker.call(lambda: 1 / 0)

    with pytest.raises(ZeroDivisionError):
        breaker.call(lambda: 1 / 0)

    # Should be open
    assert breaker.state.name == "OPEN"

    # Should reject requests
    with pytest.raises(ExchangeError):
        breaker.call(lambda: "success")

    # Wait for recovery timeout
    import time
    time.sleep(0.2)

    # Should attempt reset and succeed
    result = breaker.call(lambda: "success")
    assert result == "success"
    # After one success in HALF_OPEN, it should go to CLOSED
    assert breaker.state.name == "HALF_OPEN"  # Still in HALF_OPEN after first success

    # Need another success to close the circuit
    result2 = breaker.call(lambda: "success")
    assert result2 == "success"
    assert breaker.state.name == "HALF_OPEN"  # Still need one more

    # Third success should close the circuit
    result3 = breaker.call(lambda: "success")
    assert result3 == "success"
    assert breaker.state.name == "CLOSED"


# Test Fee Integration
def test_fee_integration():
    """Test fee integration in adapters."""
    config = ExchangeConfig(
        exchange_type=ExchangeType.BINANCE,
        adapter_mode=AdapterMode.DEPENDENCY_FREE,
        api_key="test",
        api_secret="test",
        dry_run=True,
        fees=Fees(maker_fee_bps=-0.05, taker_fee_bps=0.1)
    )

    adapter = ExchangeAdapterFactory.create_adapter(config)
    fees = adapter.get_fees()

    assert fees.maker_fee_bps == -0.05
    assert fees.taker_fee_bps == 0.1
    assert fees.maker_fee_rate == -0.000005  # -0.05 bps as decimal
    assert fees.taker_fee_rate == 0.00001    # 0.1 bps as decimal


# Test Order Operations
def test_order_validation():
    """Test order validation through unified interface."""
    config = ExchangeConfig(
        exchange_type=ExchangeType.BINANCE,
        adapter_mode=AdapterMode.DEPENDENCY_FREE,
        api_key="test",
        api_secret="test",
        dry_run=True
    )

    adapter = ExchangeAdapterFactory.create_adapter(config)

    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.LIMIT,
        quantity=0.001,
        price=50000.0
    )

    # Should validate and potentially modify the request
    validated = adapter.validate_order(request)
    assert validated.symbol == "BTCUSDT"
    assert validated.side == Side.BUY


def test_symbol_info_retrieval():
    """Test symbol information retrieval."""
    config = ExchangeConfig(
        exchange_type=ExchangeType.BINANCE,
        adapter_mode=AdapterMode.DEPENDENCY_FREE,
        api_key="test",
        api_secret="test",
        dry_run=True
    )

    adapter = ExchangeAdapterFactory.create_adapter(config)

    info = adapter.get_symbol_info("BTCUSDT")
    assert info.symbol == "BTCUSDT"
    assert info.base == "BTC"
    assert info.quote == "USDT"
    assert info.min_qty > 0
    assert info.min_notional >= 0


# Integration Tests
def test_end_to_end_adapter_creation():
    """Test end-to-end adapter creation and basic operations."""
    # Create adapter
    adapter = create_exchange_adapter(
        "binance",
        api_key="test",
        api_secret="test",
        dry_run=True,
        fees=Fees(maker_fee_bps=-0.02, taker_fee_bps=0.08)
    )

    # Test basic properties
    assert adapter.exchange_name == "binance"
    assert adapter.is_dry_run() is True

    # Test fee configuration
    fees = adapter.get_fees()
    assert fees.maker_fee_bps == -0.02
    assert fees.taker_fee_bps == 0.08

    # Test symbol info
    info = adapter.get_symbol_info("BTCUSDT")
    assert info.symbol == "BTCUSDT"

    # Test order validation
    request = OrderRequest(
        symbol="BTCUSDT",
        side=Side.BUY,
        type=OrderType.MARKET,
        quantity=0.001
    )

    validated = adapter.validate_order(request)
    assert validated.client_order_id is not None
    assert validated.client_order_id.startswith("oid_")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
