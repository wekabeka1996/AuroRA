from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
import yaml


@dataclass
class AuroraConfig:
    enabled: bool
    dd_day_limit_pct: float
    inventory_cap_usdt: float
    latency_guard_ms: int
    cooloff_base_sec: int


@dataclass
class RiskConfig:
    pi_min_bps: float


@dataclass
class SlippageConfig:
    eta_fraction_of_b: float


@dataclass
class LoggingConfig:
    path: str
    level: Literal["DEBUG", "INFO", "WARNING", "ERROR"]


@dataclass
class PolicyShimConfig:
    no_op_streak_to_cooloff: int
    action_ratio_floor_10m: float
    prefer_bias_weight: float


@dataclass
class ChatConfig:
    commands_enabled: bool


@dataclass
class AppConfig:
    aurora: AuroraConfig
    risk: RiskConfig
    slippage: SlippageConfig
    logging: LoggingConfig
    policy_shim: PolicyShimConfig
    chat: ChatConfig


class SprtConfigModel(BaseModel):
    # pydantic v2: forbid extra fields, optionally make immutable
    model_config = ConfigDict(extra="forbid", frozen=True)
    enabled: bool = Field(default=True)
    # Either provide A/B directly or alpha/beta to derive thresholds
    alpha: float | None = Field(default=None)
    beta: float | None = Field(default=None)
    sigma: float = Field(default=1.0)
    A: float = Field(default=2.0)
    B: float = Field(default=-2.0)
    max_obs: int = Field(default=10)


def load_config(path: str | os.PathLike) -> dict:
    p = Path(path)
    with p.open('r', encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def load_sprt_cfg(yaml_cfg: dict) -> SprtConfigModel:
    base = SprtConfigModel(**(yaml_cfg.get("sprt", {}) or {}))

    def _maybe(env: str, cast):
        v = os.getenv(env)
        if v is None:
            return None
        try:
            return cast(v)
        except Exception:
            return None

    overrides = {
        "enabled": _maybe("AURORA_SPRT_ENABLED", lambda x: str(x).lower() in {"1", "true", "yes"}),
        "alpha": _maybe("AURORA_SPRT_ALPHA", float),
        "beta": _maybe("AURORA_SPRT_BETA", float),
        "sigma": _maybe("AURORA_SPRT_SIGMA", float),
        "A": _maybe("AURORA_SPRT_A", float),
        "B": _maybe("AURORA_SPRT_B", float),
        "max_obs": _maybe("AURORA_SPRT_MAX_OBS", int),
    }
    overrides = {k: v for k, v in overrides.items() if v is not None}
    cfg = base.model_copy(update=overrides)
    # If alpha/beta provided (via YAML or env), derive A/B unless explicitly overridden by env A/B
    try:
        from core.scalper.sprt import thresholds_from_alpha_beta
        if cfg.alpha is not None and cfg.beta is not None:
            A, B = thresholds_from_alpha_beta(cfg.alpha, cfg.beta)
            # Respect explicit A/B overrides when provided in overrides
            if "A" not in overrides:
                cfg = cfg.model_copy(update={"A": A})
            if "B" not in overrides:
                cfg = cfg.model_copy(update={"B": B})
    except Exception:
        pass
    return cfg
