from __future__ import annotations

"""
Unified Exchange Adapter Interface
==================================

Provides a unified interface for all exchange adapters with:
- Factory pattern for creating exchange instances
- Unified configuration management
- Fee-aware order execution
- Comprehensive error handling and logging
- Support for both dependency-free and CCXT-based implementations
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Any, Dict, List, Mapping, Optional, Protocol, Type, Union

from core.execution.exchange.binance import BinanceExchange
from core.execution.exchange.common import (
    AbstractExchange,
    ExchangeError,
    Fees,
    OrderRequest,
    OrderResult,
    RateLimitError,
    SymbolInfo,
    ValidationError,
)
from core.execution.exchange.error_handling import exchange_operation_context
from core.execution.exchange.gate import GateExchange

logger = logging.getLogger(__name__)


class ExchangeType(str, Enum):
    """Supported exchange types."""

    BINANCE = "binance"
    GATE = "gate"
    BINANCE_CCXT = "binance_ccxt"


class AdapterMode(str, Enum):
    """Adapter implementation modes."""

    DEPENDENCY_FREE = "dependency_free"  # Pure Python implementation
    CCXT = "ccxt"  # CCXT-based implementation


@dataclass
class ExchangeConfig:
    """Configuration for exchange adapter."""

    exchange_type: ExchangeType
    adapter_mode: AdapterMode
    api_key: str
    api_secret: str
    base_url: Optional[str] = None
    futures: bool = False
    testnet: bool = True
    recv_window_ms: int = 5000
    timeout_ms: int = 20000
    enable_rate_limit: bool = True
    dry_run: bool = True
    fees: Optional[Fees] = None

    @classmethod
    def from_ssot_config(cls, exchange_name: str) -> "ExchangeConfig":
        """Create ExchangeConfig from SSOT configuration using the SSOT manager.

        This delegates to core.execution.exchange.config to ensure a single
        source of truth and avoid duplicated parsing logic.
        """
        try:
            from core.execution.exchange.config import get_config_manager

            mgr = get_config_manager()
            ssot = mgr.get_config(exchange_name)
            if ssot is None:
                # If no persisted config found, try to create a default one and keep in-memory
                # Default to the exchange_name as type when possible
                try:
                    ex_type = ExchangeType(exchange_name)
                except Exception:
                    ex_type = ExchangeType.BINANCE
                ssot = mgr.create_config(exchange_name, ex_type)
            return ssot.to_adapter_config()
        except Exception as e:
            logger.warning(
                f"Failed to load SSOT config via manager for {exchange_name}: {e}"
            )
            # Conservative fallback
            return cls(
                exchange_type=ExchangeType.BINANCE,
                adapter_mode=AdapterMode.DEPENDENCY_FREE,
                api_key="",
                api_secret="",
                dry_run=True,
                fees=Fees(maker_fee_bps=0.1, taker_fee_bps=0.1),
            )


class HttpClientProtocol(Protocol):
    """HTTP client protocol for dependency injection."""

    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, object]] = None,
        headers: Optional[Mapping[str, str]] = None,
        json: Optional[object] = None,
    ) -> Mapping[str, object]: ...


class UnifiedExchangeAdapter(ABC):
    """Abstract base class for unified exchange adapters."""

    def __init__(
        self, config: ExchangeConfig, http_client: Optional[HttpClientProtocol] = None
    ):
        self.config = config
        self.http_client = http_client
        self._exchange: Optional[AbstractExchange] = None
        self._logger = logging.getLogger(f"{__name__}.{self.__class__.__name__}")

    @property
    @abstractmethod
    def exchange_name(self) -> str:
        """Get the exchange name."""
        pass

    @abstractmethod
    def _create_exchange_instance(self) -> AbstractExchange:
        """Create the underlying exchange instance."""
        pass

    def _get_exchange(self) -> AbstractExchange:
        """Get or create the underlying exchange instance."""
        if self._exchange is None:
            self._exchange = self._create_exchange_instance()
        return self._exchange

    # Unified interface methods
    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        """Get symbol information."""
        with exchange_operation_context(
            self.exchange_name, "get_symbol_info", symbol=symbol
        ):
            return self._get_exchange().get_symbol_info(symbol)

    def validate_order(self, request: OrderRequest) -> OrderRequest:
        """Validate and normalize order request."""
        with exchange_operation_context(
            self.exchange_name,
            "validate_order",
            symbol=request.symbol,
            client_order_id=request.client_order_id,
        ):
            return self._get_exchange().validate_order(request)

    def place_order(self, request: OrderRequest) -> OrderResult:
        """Place an order."""
        with exchange_operation_context(
            self.exchange_name,
            "place_order",
            symbol=request.symbol,
            client_order_id=request.client_order_id,
        ) as ctx:
            validated_request = self.validate_order(request)
            result = self._get_exchange().place_order(validated_request)
            self._logger.info(f"Order placed: {result.order_id} ({result.status})")
            return result

    def cancel_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Cancel an order."""
        with exchange_operation_context(
            self.exchange_name,
            "cancel_order",
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        ):
            result = self._get_exchange().cancel_order(
                symbol, order_id, client_order_id
            )
            self._logger.info(f"Order cancelled: {order_id or client_order_id}")
            return dict(result)

    def get_order(
        self,
        symbol: str,
        order_id: Optional[str] = None,
        client_order_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Get order information."""
        with exchange_operation_context(
            self.exchange_name,
            "get_order",
            symbol=symbol,
            order_id=order_id,
            client_order_id=client_order_id,
        ):
            result = self._get_exchange().get_order(symbol, order_id, client_order_id)
            return dict(result)  # Convert Mapping to Dict

    def get_fees(self) -> Fees:
        """Get exchange fees configuration."""
        return self.config.fees or Fees(maker_fee_bps=0.1, taker_fee_bps=0.1)

    def is_dry_run(self) -> bool:
        """Check if adapter is in dry run mode."""
        return self.config.dry_run


class BinanceAdapter(UnifiedExchangeAdapter):
    """Binance exchange adapter."""

    @property
    def exchange_name(self) -> str:
        return "binance"

    def _create_exchange_instance(self) -> AbstractExchange:
        """Create Binance exchange instance."""
        base_url = self.config.base_url
        if self.config.testnet and not base_url:
            base_url = (
                "https://testnet.binance.vision"
                if not self.config.futures
                else "https://testnet.binancefuture.com"
            )

        return BinanceExchange(
            api_key=self.config.api_key,
            api_secret=self.config.api_secret,
            http=self.http_client,
            futures=self.config.futures,
            base_url=base_url,
        )


class GateAdapter(UnifiedExchangeAdapter):
    """Gate.io exchange adapter."""

    @property
    def exchange_name(self) -> str:
        return "gate"

    def _create_exchange_instance(self) -> AbstractExchange:
        """Create Gate exchange instance."""
        base_url = self.config.base_url or "https://fx-api-testnet.gateio.ws/api/v4"

        return GateExchange(
            api_key=self.config.api_key,
            api_secret=self.config.api_secret,
            http=self.http_client,
            base_url=base_url,
        )


class CCXTExchangeWrapper(AbstractExchange):
    """Wrapper to make CCXT adapter compatible with AbstractExchange interface."""

    def __init__(self, ccxt_adapter):
        super().__init__(http=None)  # CCXT handles its own HTTP
        self._ccxt_adapter = ccxt_adapter
        self.name = "binance_ccxt"  # Set name directly instead of property

    def get_symbol_info(self, symbol: str) -> SymbolInfo:
        """Get symbol info from CCXT adapter."""
        # This is a simplified implementation - in production you'd need to
        # extract symbol info from CCXT's market data
        return SymbolInfo(
            symbol=symbol,
            base=symbol.split("/")[0] if "/" in symbol else symbol[:-4],
            quote=symbol.split("/")[1] if "/" in symbol else symbol[-4:],
            tick_size=0.01,
            step_size=0.001,
            min_qty=0.001,
            min_notional=5.0,
        )

    def place_order(self, req: OrderRequest) -> OrderResult:
        """Place order via CCXT adapter."""
        # Convert to CCXT format and place order
        side = req.side.value.lower()
        order_type = req.type.value.lower()
        qty = req.quantity
        price = req.price

        # Call CCXT adapter
        result = self._ccxt_adapter.place_order(side, qty, price)

        # Convert back to our format
        from core.execution.exchange.common import Fill

        fills = []
        if not self._ccxt_adapter.dry:
            # In real execution, we'd parse actual fills
            fills = [
                Fill(
                    price=price or 0.0,
                    qty=qty,
                    fee=0.0,
                    fee_asset="USDT",
                    ts_ns=self.server_time_ns_hint(),
                )
            ]

        return OrderResult(
            order_id=str(result.get("id", "")),
            client_order_id=req.client_order_id or "",
            status=result.get("status", "NEW"),
            executed_qty=qty if not self._ccxt_adapter.dry else 0.0,
            cumm_quote_cost=(price or 0.0) * qty if price else 0.0,
            fills=fills,
            ts_ns=self.server_time_ns_hint(),
            raw=result,
        )

    def cancel_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Mapping[str, object]:
        """Cancel order via CCXT adapter."""
        return self._ccxt_adapter.cancel_all()  # Simplified - cancel all for now

    def get_order(
        self,
        symbol: str,
        order_id: str | None = None,
        client_order_id: str | None = None,
    ) -> Mapping[str, object]:
        """Get order info - simplified implementation."""
        return {"status": "unknown", "id": order_id}


class CCXTBinanceAdapter(UnifiedExchangeAdapter):
    """CCXT-based Binance adapter."""

    @property
    def exchange_name(self) -> str:
        return "binance_ccxt"

    def _create_exchange_instance(self) -> AbstractExchange:
        """Create CCXT-based exchange instance."""
        try:
            from skalp_bot.exch.ccxt_binance import CCXTBinanceAdapter as CCXTAdapter

            # Convert our config to CCXT format
            ccxt_config = {
                "exchange": {
                    "id": "binanceusdm" if self.config.futures else "binance",
                    "testnet": self.config.testnet,
                    "use_futures": self.config.futures,
                    "recv_window_ms": self.config.recv_window_ms,
                    "timeout_ms": self.config.timeout_ms,
                    "api_key_env": "BINANCE_API_KEY",
                    "api_secret_env": "BINANCE_API_SECRET",
                },
                "dry_run": self.config.dry_run,
                "symbol": "BTC/USDT",  # Default, can be overridden
            }

            # Set environment variables for credentials
            import os

            if self.config.api_key:
                os.environ["BINANCE_API_KEY"] = self.config.api_key
            if self.config.api_secret:
                os.environ["BINANCE_API_SECRET"] = self.config.api_secret

            # Create CCXT adapter
            return CCXTExchangeWrapper(CCXTAdapter(ccxt_config))

        except ImportError as e:
            raise ExchangeError(f"CCXT not available: {e}") from e


class ExchangeAdapterFactory:
    """Factory for creating exchange adapters."""

    _adapters: Dict[str, Type[UnifiedExchangeAdapter]] = {
        ExchangeType.BINANCE: BinanceAdapter,
        ExchangeType.GATE: GateAdapter,
        ExchangeType.BINANCE_CCXT: CCXTBinanceAdapter,
    }

    @classmethod
    def create_adapter(
        cls, config: ExchangeConfig, http_client: Optional[HttpClientProtocol] = None
    ) -> UnifiedExchangeAdapter:
        """Create an exchange adapter instance."""
        adapter_class = cls._adapters.get(config.exchange_type)
        if not adapter_class:
            raise ValueError(f"Unsupported exchange type: {config.exchange_type}")

        try:
            adapter = adapter_class(config, http_client)
            logger.info(
                f"Created {config.adapter_mode.value} adapter for {config.exchange_type.value}"
            )
            return adapter
        except Exception as e:
            logger.error(
                f"Failed to create adapter for {config.exchange_type.value}: {e}"
            )
            raise ExchangeError(f"Adapter creation failed: {e}") from e

    @classmethod
    def create_from_ssot(
        cls, exchange_name: str, http_client: Optional[HttpClientProtocol] = None
    ) -> UnifiedExchangeAdapter:
        """Create adapter from SSOT configuration."""
        config = ExchangeConfig.from_ssot_config(exchange_name)
        return cls.create_adapter(config, http_client)

    @classmethod
    def get_supported_exchanges(cls) -> List[str]:
        """Get list of supported exchange types."""
        return list(cls._adapters.keys())


# Convenience functions
def create_exchange_adapter(
    exchange_name: str,
    api_key: str = "",
    api_secret: str = "",
    adapter_mode: str = "dependency_free",
    **kwargs,
) -> UnifiedExchangeAdapter:
    """Convenience function to create exchange adapter."""
    exchange_type = ExchangeType(exchange_name.lower())
    adapter_mode_enum = AdapterMode(adapter_mode.lower())

    config = ExchangeConfig(
        exchange_type=exchange_type,
        adapter_mode=adapter_mode_enum,
        api_key=api_key,
        api_secret=api_secret,
        **kwargs,
    )

    return ExchangeAdapterFactory.create_adapter(config)


__all__ = [
    "ExchangeType",
    "AdapterMode",
    "ExchangeConfig",
    "HttpClientProtocol",
    "UnifiedExchangeAdapter",
    "BinanceAdapter",
    "GateAdapter",
    "CCXTBinanceAdapter",
    "ExchangeAdapterFactory",
    "create_exchange_adapter",
]
