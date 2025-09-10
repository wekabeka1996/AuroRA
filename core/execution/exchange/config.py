from __future__ import annotations

"""
Exchange Configuration Management
=================================

Provides SSOT (Single Source of Truth) configuration management for exchanges:
- Centralized exchange configuration
- Environment-specific settings
- Fee configuration per exchange
- Validation and defaults
- Configuration persistence and loading
"""

import json
import logging
import os
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.execution.exchange.common import Fees
from core.execution.exchange.unified import AdapterMode, ExchangeType

logger = logging.getLogger(__name__)


@dataclass
class ExchangeCredentials:
    """Exchange API credentials."""

    api_key: str
    api_secret: str

    @classmethod
    def from_env(cls, exchange_name: str) -> "ExchangeCredentials":
        """Load credentials from environment variables."""
        key_env = f"{exchange_name.upper()}_API_KEY"
        secret_env = f"{exchange_name.upper()}_API_SECRET"

        api_key = os.getenv(key_env, "")
        api_secret = os.getenv(secret_env, "")

        return cls(api_key=api_key, api_secret=api_secret)


@dataclass
class ExchangeSettings:
    """Exchange-specific settings."""

    type: ExchangeType
    adapter_mode: AdapterMode
    base_url: Optional[str]
    futures: bool
    testnet: bool
    recv_window_ms: int
    timeout_ms: int
    enable_rate_limit: bool
    dry_run: bool
    symbol: str
    leverage: Optional[float]

    @classmethod
    def get_defaults(cls, exchange_type: ExchangeType) -> "ExchangeSettings":
        """Get default settings for exchange type."""
        defaults = {
            ExchangeType.BINANCE: {
                "base_url": None,
                "futures": False,
                "testnet": True,
                "recv_window_ms": 5000,
                "timeout_ms": 20000,
                "enable_rate_limit": True,
                "dry_run": True,
                "symbol": "BTC/USDT",
                "leverage": None,
            },
            ExchangeType.GATE: {
                "base_url": None,
                "futures": False,
                "testnet": True,
                "recv_window_ms": 5000,
                "timeout_ms": 20000,
                "enable_rate_limit": True,
                "dry_run": True,
                "symbol": "BTC_USDT",
                "leverage": None,
            },
            ExchangeType.BINANCE_CCXT: {
                "base_url": None,
                "futures": False,
                "testnet": True,
                "recv_window_ms": 5000,
                "timeout_ms": 20000,
                "enable_rate_limit": True,
                "dry_run": True,
                "symbol": "BTC/USDT",
                "leverage": None,
            },
        }

        default_settings = defaults.get(exchange_type, defaults[ExchangeType.BINANCE])
        return cls(
            type=exchange_type,
            adapter_mode=AdapterMode.DEPENDENCY_FREE,
            **default_settings,
        )


@dataclass
class ExchangeConfig:
    """Complete exchange configuration."""

    name: str
    credentials: ExchangeCredentials
    settings: ExchangeSettings
    fees: Fees
    metadata: Dict[str, Any]

    @classmethod
    def create(
        cls,
        name: str,
        exchange_type: ExchangeType,
        api_key: str = "",
        api_secret: str = "",
        **overrides,
    ) -> "ExchangeConfig":
        """Create a complete exchange configuration."""

        # Load credentials
        if not api_key or not api_secret:
            credentials = ExchangeCredentials.from_env(name)
        else:
            credentials = ExchangeCredentials(api_key=api_key, api_secret=api_secret)

        # Get default settings and apply overrides
        settings = ExchangeSettings.get_defaults(exchange_type)

        # Handle fees separately
        fees_override = overrides.pop("fees", None)
        if fees_override:
            fees = fees_override
        else:
            fees = Fees.from_exchange_config(name)

        # Apply remaining overrides to settings (preserve enum types)
        for key, value in overrides.items():
            if key == "adapter_mode":
                settings.adapter_mode = (
                    value if isinstance(value, AdapterMode) else AdapterMode(value)
                )
                continue
            if hasattr(settings, key):
                setattr(settings, key, value)

        # Default metadata
        metadata = {
            "created_at": None,
            "updated_at": None,
            "version": "1.0",
            "description": f"{name} exchange configuration",
        }

        return cls(
            name=name,
            credentials=credentials,
            settings=settings,
            fees=fees,
            metadata=metadata,
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "name": self.name,
            "credentials": asdict(self.credentials),
            "settings": asdict(self.settings),
            "fees": {
                "maker_fee_bps": self.fees.maker_fee_bps,
                "taker_fee_bps": self.fees.taker_fee_bps,
            },
            "metadata": self.metadata,
        }

    # ---- SSOT -> Adapter DTO mapping ----
    def to_adapter_config(self):
        """Map SSOT ExchangeConfig to adapter runtime config (unified.ExchangeConfig).

        Import is local to avoid an import cycle at module import time.
        """
        from core.execution.exchange.unified import ExchangeConfig as AdapterConfig

        return AdapterConfig(
            exchange_type=self.settings.type,
            adapter_mode=self.settings.adapter_mode,
            api_key=self.credentials.api_key,
            api_secret=self.credentials.api_secret,
            base_url=self.settings.base_url,
            futures=self.settings.futures,
            testnet=self.settings.testnet,
            recv_window_ms=self.settings.recv_window_ms,
            timeout_ms=self.settings.timeout_ms,
            enable_rate_limit=self.settings.enable_rate_limit,
            dry_run=self.settings.dry_run,
            fees=self.fees,
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ExchangeConfig":
        """Create from dictionary."""
        credentials = ExchangeCredentials(**data["credentials"])
        settings_data = data["settings"]
        settings = ExchangeSettings(
            type=ExchangeType(settings_data["type"]),
            adapter_mode=AdapterMode(settings_data["adapter_mode"]),
            base_url=settings_data.get("base_url"),
            futures=settings_data["futures"],
            testnet=settings_data["testnet"],
            recv_window_ms=settings_data["recv_window_ms"],
            timeout_ms=settings_data["timeout_ms"],
            enable_rate_limit=settings_data["enable_rate_limit"],
            dry_run=settings_data["dry_run"],
            symbol=settings_data["symbol"],
            leverage=settings_data.get("leverage"),
        )
        fees_data = data["fees"]
        fees = Fees(
            maker_fee_bps=fees_data["maker_fee_bps"],
            taker_fee_bps=fees_data["taker_fee_bps"],
        )

        return cls(
            name=data["name"],
            credentials=credentials,
            settings=settings,
            fees=fees,
            metadata=data.get("metadata", {}),
        )

    def is_valid(self) -> bool:
        """Validate configuration."""
        # Check required fields
        if not self.name:
            return False

        # Check credentials for non-dry-run
        if not self.settings.dry_run:
            if not self.credentials.api_key or not self.credentials.api_secret:
                return False

        # Check fee values are reasonable
        if self.fees.maker_fee_bps < -100 or self.fees.maker_fee_bps > 100:
            return False
        if self.fees.taker_fee_bps < 0 or self.fees.taker_fee_bps > 100:
            return False

        return True

    def get_summary(self) -> str:
        """Get configuration summary."""
        return (
            f"Exchange: {self.name} ({self.settings.type.value})\n"
            f"Mode: {self.settings.adapter_mode.value}\n"
            f"Environment: {'Testnet' if self.settings.testnet else 'Live'}\n"
            f"Dry Run: {self.settings.dry_run}\n"
            f"Fees: Maker={self.fees.maker_fee_bps}bps, Taker={self.fees.taker_fee_bps}bps\n"
            f"Symbol: {self.settings.symbol}"
        )


class ExchangeConfigManager:
    """Manager for exchange configurations."""

    def __init__(self, config_dir: Optional[Path] = None):
        self.config_dir = config_dir or Path("configs/exchanges")
        self.config_dir.mkdir(parents=True, exist_ok=True)
        self._configs: Dict[str, ExchangeConfig] = {}
        self._load_configs()

    def _load_configs(self):
        """Load all configurations from disk."""
        for config_file in self.config_dir.glob("*.json"):
            try:
                with open(config_file, "r") as f:
                    data = json.load(f)
                config = ExchangeConfig.from_dict(data)
                self._configs[config.name] = config
                logger.info(f"Loaded config for {config.name}")
            except Exception as e:
                logger.warning(f"Failed to load config {config_file}: {e}")

    def _save_config(self, config: ExchangeConfig):
        """Save configuration to disk."""
        config_file = self.config_dir / f"{config.name}.json"
        try:
            with open(config_file, "w") as f:
                json.dump(config.to_dict(), f, indent=2)
            logger.info(f"Saved config for {config.name}")
        except Exception as e:
            logger.error(f"Failed to save config {config.name}: {e}")

    def create_config(
        self,
        name: str,
        exchange_type: ExchangeType,
        api_key: str = "",
        api_secret: str = "",
        **overrides,
    ) -> ExchangeConfig:
        """Create and store a new configuration."""
        config = ExchangeConfig.create(
            name, exchange_type, api_key, api_secret, **overrides
        )
        self._configs[name] = config
        self._save_config(config)
        return config

    def get_config(self, name: str) -> Optional[ExchangeConfig]:
        """Get configuration by name."""
        return self._configs.get(name)

    def list_configs(self) -> List[str]:
        """List all configuration names."""
        return list(self._configs.keys())

    def update_config(self, name: str, **updates) -> Optional[ExchangeConfig]:
        """Update configuration."""
        config = self._configs.get(name)
        if not config:
            return None

        # Update settings
        for key, value in updates.items():
            if hasattr(config.settings, key):
                setattr(config.settings, key, value)
            elif hasattr(config.fees, key):
                setattr(config.fees, key, value)
            elif hasattr(config.credentials, key):
                setattr(config.credentials, key, value)

        # Validate and save
        if config.is_valid():
            self._save_config(config)
            return config
        else:
            logger.error(f"Updated config for {name} is invalid")
            return None

    def delete_config(self, name: str) -> bool:
        """Delete configuration."""
        if name in self._configs:
            config_file = self.config_dir / f"{name}.json"
            try:
                config_file.unlink(missing_ok=True)
                del self._configs[name]
                logger.info(f"Deleted config for {name}")
                return True
            except Exception as e:
                logger.error(f"Failed to delete config {name}: {e}")
        return False

    def get_exchange_adapter_config(self, name: str):
        """Get configuration in adapter format."""
        config = self.get_config(name)
        if not config:
            return None

        # Use the SSOT->adapter mapper to avoid duplication
        return config.to_adapter_config()


# Global configuration manager instance
_config_manager: Optional[ExchangeConfigManager] = None


def get_config_manager() -> ExchangeConfigManager:
    """Get global configuration manager instance."""
    global _config_manager
    if _config_manager is None:
        _config_manager = ExchangeConfigManager()
    return _config_manager


def create_exchange_config(name: str, exchange_type: str, **kwargs) -> ExchangeConfig:
    """Convenience function to create exchange configuration."""
    return get_config_manager().create_config(
        name, ExchangeType(exchange_type), **kwargs
    )


def get_exchange_config(name: str) -> Optional[ExchangeConfig]:
    """Convenience function to get exchange configuration."""
    return get_config_manager().get_config(name)


__all__ = [
    "ExchangeCredentials",
    "ExchangeSettings",
    "ExchangeConfig",
    "ExchangeConfigManager",
    "get_config_manager",
    "create_exchange_config",
    "get_exchange_config",
]
