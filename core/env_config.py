# -*- coding: utf-8 -*-
"""Environment configuration loader for Aurora.

Extended to support a controlled testnet (USDM futures) mode in addition to the
existing live-only enforcement. Default remains live. Testnet enablement is
strictly opt-in via BINANCE_ENV=testnet and requires the presence ONLY of
testnet credential variables. Mixed key presence (live + testnet) is rejected
to avoid accidental cross-mode leakage.

Modes:
    live    : production keys + endpoints
    testnet : testnet keys + testnet futures endpoints (spot not supported here)

Notes:
    * Acceptance / shadow logic lives outside (runner decides DRY_RUN etc.)
    * This module is intentionally minimal: no network probes, only env guards.
"""
import os
from dataclasses import dataclass

try:
    from dotenv import load_dotenv
except ImportError:
    def load_dotenv():
        pass  # Fallback if python-dotenv not available


@dataclass
class BinanceCfg:
    env: str            # 'live' | 'testnet'
    api_key: str
    api_secret: str
    base_url: str       # REST base
    ws_url: str         # WS base


def load_binance_cfg() -> BinanceCfg:
    """Load Binance configuration (live or testnet) from environment.

    Environment variables (only one credential set must be present):
      BINANCE_ENV = live | testnet (default live)

      Live creds:
        BINANCE_API_KEY_LIVE
        BINANCE_API_SECRET_LIVE
      Testnet creds:
        BINANCE_API_KEY_TESTNET
        BINANCE_API_SECRET_TESTNET

    Returns:
        BinanceCfg

    Raises:
        RuntimeError: On invalid/mixed configuration or missing credentials.
    """
    load_dotenv()

    env = (os.getenv("BINANCE_ENV") or "live").lower().strip()
    if env not in {"live", "testnet"}:
        raise RuntimeError(f"Unsupported BINANCE_ENV='{env}' (expected live|testnet)")

    live_key = os.getenv("BINANCE_API_KEY_LIVE")
    live_sec = os.getenv("BINANCE_API_SECRET_LIVE")
    test_key = os.getenv("BINANCE_API_KEY_TESTNET")
    test_sec = os.getenv("BINANCE_API_SECRET_TESTNET")

    # Mutual exclusion: do not allow both sets simultaneously (reduces operator error risk)
    if (live_key or live_sec) and (test_key or test_sec):
        raise RuntimeError("Both live and testnet credential variables present – remove one set before continuing")

    if env == "live":
        if not (live_key and live_sec):
            raise RuntimeError("Missing live credentials (BINANCE_API_KEY_LIVE / BINANCE_API_SECRET_LIVE)")
        base_url = os.getenv("BINANCE_USDM_BASE_URL", "https://fapi.binance.com")
        ws_url = os.getenv("BINANCE_USDM_WS_URL", "wss://fstream.binance.com/stream")
        return BinanceCfg(env="live", api_key=live_key, api_secret=live_sec, base_url=base_url, ws_url=ws_url)

    # testnet branch
    if not (test_key and test_sec):
        raise RuntimeError("Missing testnet credentials (BINANCE_API_KEY_TESTNET / BINANCE_API_SECRET_TESTNET)")
    base_url = os.getenv("BINANCE_USDM_BASE_URL_TESTNET", "https://testnet.binancefuture.com")
    ws_url = os.getenv("BINANCE_USDM_WS_URL_TESTNET", "wss://stream.binancefuture.com/stream")
    return BinanceCfg(env="testnet", api_key=test_key, api_secret=test_sec, base_url=base_url, ws_url=ws_url)


def load_binance_futures_cfg() -> BinanceCfg:  # Backwards compatibility helper
    return load_binance_cfg()


def validate_aurora_mode() -> str:
    """Validate AURORA_MODE (now accepts live, testnet, and legacy prod).

    Aurora now supports both live and testnet modes. The separation between
    production and testnet is handled by BINANCE_ENV configuration.
    Legacy 'prod' is mapped to 'live' for backward compatibility.
    """
    aurora_mode = os.getenv("AURORA_MODE", "live").lower().strip()
    
    # Handle legacy 'prod' mode as 'live' for backward compatibility
    if aurora_mode == "prod":
        aurora_mode = "live"
    
    if aurora_mode not in ['live', 'testnet']:
        raise RuntimeError(f"AURORA_MODE must be 'live' or 'testnet' (got: {aurora_mode})")
    return aurora_mode


def get_runtime_mode() -> tuple[str, str]:
    """Get validated runtime configuration.
    
    Returns:
        tuple[str, str]: (aurora_mode, binance_env) with smart defaults
        
    Raises:
        RuntimeError: On invalid configuration combinations
    """
    aurora_mode = validate_aurora_mode()
    binance_env = os.getenv("BINANCE_ENV", "live" if aurora_mode == "live" else "testnet")
    
    # Validation: testnet mode requires testnet environment
    if aurora_mode == "testnet" and binance_env != "testnet":
        raise RuntimeError("AURORA_MODE=testnet requires BINANCE_ENV=testnet")
    
    return aurora_mode, binance_env