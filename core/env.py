from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Any


def _to_bool(v: str | None, default: bool = False) -> bool:
    if v is None:
        return default
    return str(v).strip().lower() in {"1", "true", "yes", "on"}


def _to_float(v: str | None, default: float) -> float:
    try:
        return float(v) if v is not None else default
    except Exception:
        return default


def _to_int(v: str | None, default: int) -> int:
    try:
        return int(float(v)) if v is not None else default
    except Exception:
        return default


@dataclass
class EnvConfig:
    # core account/exchange
    AURORA_MODE: str = "testnet"  # testnet|prod
    EXCHANGE_ID: str = "binanceusdm"
    EXCHANGE_TESTNET: bool = True
    EXCHANGE_USE_FUTURES: bool = True
    DRY_RUN: bool = True
    BINANCE_API_KEY: str | None = None
    BINANCE_API_SECRET: str | None = None
    BINANCE_RECV_WINDOW: int = 20000

    # pretrade/gates
    PRETRADE_ORDER_PROFILE: str = "er_before_slip"  # er_before_slip|slip_before_er
    AURORA_PI_MIN_BPS: float = 1.5
    AURORA_SLIP_FRACTION: float = 0.25
    AURORA_SPREAD_MAX_BPS: float = 50.0
    CLOCK_GUARD: str = "off"
    AURORA_SPRT_ENABLED: bool = False

    # runner/network
    AURORA_HTTP_TIMEOUT_MS: int = 120

    # sizing/ops
    AURORA_SIZE_SCALE: float = 0.05
    AURORA_MAX_CONCURRENT: int = 1

    # optional ops/push
    PUSHGATEWAY_URL: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "AURORA_MODE": self.AURORA_MODE,
            "EXCHANGE_ID": self.EXCHANGE_ID,
            "EXCHANGE_TESTNET": self.EXCHANGE_TESTNET,
            "EXCHANGE_USE_FUTURES": self.EXCHANGE_USE_FUTURES,
            "DRY_RUN": self.DRY_RUN,
            "BINANCE_API_KEY": self.BINANCE_API_KEY,
            "BINANCE_API_SECRET": self.BINANCE_API_SECRET,
            "BINANCE_RECV_WINDOW": self.BINANCE_RECV_WINDOW,
            "PRETRADE_ORDER_PROFILE": self.PRETRADE_ORDER_PROFILE,
            "AURORA_PI_MIN_BPS": self.AURORA_PI_MIN_BPS,
            "AURORA_SLIP_FRACTION": self.AURORA_SLIP_FRACTION,
            "AURORA_SPREAD_MAX_BPS": self.AURORA_SPREAD_MAX_BPS,
            "CLOCK_GUARD": self.CLOCK_GUARD,
            "AURORA_SPRT_ENABLED": self.AURORA_SPRT_ENABLED,
            "AURORA_HTTP_TIMEOUT_MS": self.AURORA_HTTP_TIMEOUT_MS,
            "AURORA_SIZE_SCALE": self.AURORA_SIZE_SCALE,
            "AURORA_MAX_CONCURRENT": self.AURORA_MAX_CONCURRENT,
            "PUSHGATEWAY_URL": self.PUSHGATEWAY_URL,
        }


_ALIASES = {
    # map older variable names to canonical ones where used in codebase
    # API service currently reads AURORA_LMAX_MS for latency immediate cutoff
    "AURORA_LATENCY_GUARD_MS": "AURORA_LMAX_MS",
}


def apply_aliases_env():
    for old, new in _ALIASES.items():
        if old in os.environ and new not in os.environ:
            os.environ[new] = os.environ[old]


def load_env(dotenv: bool = True, path: Path | None = None) -> EnvConfig:
    """Load .env into process env and return parsed EnvConfig.

    If python-dotenv is not available, we still proceed using existing env.
    """
    if dotenv:
        try:
            from dotenv import load_dotenv as _load
            _load(dotenv_path=str(path) if path else None)
        except Exception:
            pass

    # normalize aliases before reading
    apply_aliases_env()

    return EnvConfig(
        AURORA_MODE=os.getenv("AURORA_MODE", "testnet"),
        EXCHANGE_ID=os.getenv("EXCHANGE_ID", "binanceusdm").strip(),
        EXCHANGE_TESTNET=_to_bool(os.getenv("EXCHANGE_TESTNET"), True),
        EXCHANGE_USE_FUTURES=_to_bool(os.getenv("EXCHANGE_USE_FUTURES"), True),
        DRY_RUN=_to_bool(os.getenv("DRY_RUN"), True),
        BINANCE_API_KEY=os.getenv("BINANCE_API_KEY"),
        BINANCE_API_SECRET=os.getenv("BINANCE_API_SECRET"),
        BINANCE_RECV_WINDOW=_to_int(os.getenv("BINANCE_RECV_WINDOW"), 20000),
        PRETRADE_ORDER_PROFILE=os.getenv("PRETRADE_ORDER_PROFILE", "er_before_slip"),
        AURORA_PI_MIN_BPS=_to_float(os.getenv("AURORA_PI_MIN_BPS"), 1.5),
        AURORA_SLIP_FRACTION=_to_float(os.getenv("AURORA_SLIP_FRACTION"), 0.25),
        AURORA_SPREAD_MAX_BPS=_to_float(os.getenv("AURORA_SPREAD_MAX_BPS"), 50.0),
        CLOCK_GUARD=os.getenv("CLOCK_GUARD", "off"),
        AURORA_SPRT_ENABLED=_to_bool(os.getenv("AURORA_SPRT_ENABLED"), False),
        AURORA_HTTP_TIMEOUT_MS=_to_int(os.getenv("AURORA_HTTP_TIMEOUT_MS"), 120),
        AURORA_SIZE_SCALE=_to_float(os.getenv("AURORA_SIZE_SCALE"), 0.05),
        AURORA_MAX_CONCURRENT=_to_int(os.getenv("AURORA_MAX_CONCURRENT"), 1),
        PUSHGATEWAY_URL=os.getenv("PUSHGATEWAY_URL"),
    )

