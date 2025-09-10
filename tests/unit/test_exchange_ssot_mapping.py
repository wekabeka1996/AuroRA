from __future__ import annotations

from core.execution.exchange import config as cfg_module
from core.execution.exchange.config import ExchangeConfigManager
from core.execution.exchange.unified import (
    AdapterMode,
    BinanceAdapter,
    ExchangeAdapterFactory,
    ExchangeType,
)


def test_ssot_to_adapter_roundtrip(tmp_path):
    # Use isolated config dir
    mgr = ExchangeConfigManager(config_dir=tmp_path)
    # Set as global manager so unified.from_ssot_config uses it
    cfg_module._config_manager = mgr

    # Create SSOT config
    cfg = mgr.create_config(
        name="binance",
        exchange_type=ExchangeType.BINANCE,
        api_key="k",
        api_secret="s",
        futures=True,
        testnet=True,
        adapter_mode=AdapterMode.DEPENDENCY_FREE,
    )

    # Map to adapter config DTO
    adapter_cfg = cfg.to_adapter_config()
    assert adapter_cfg.exchange_type == ExchangeType.BINANCE
    assert adapter_cfg.adapter_mode == AdapterMode.DEPENDENCY_FREE
    assert adapter_cfg.api_key == "k"
    assert adapter_cfg.api_secret == "s"
    assert adapter_cfg.futures is True
    assert adapter_cfg.testnet is True

    # Create adapter via factory from SSOT
    adapter = ExchangeAdapterFactory.create_from_ssot("binance")
    assert isinstance(adapter, BinanceAdapter)
    assert adapter.exchange_name == "binance"
