from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
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


# --- YAML helpers ---

def resolve_config_path(name_or_path: str | None) -> Path | None:
    """Resolve a config path from env/name.

    Accepts absolute/relative path to .yaml, or a bare name without extension.
    Search order for names: configs/<name>.yaml, skalp_bot/configs/<name>.yaml.
    Returns None when no input provided or not found.
    """
    if not name_or_path:
        return None
    p = Path(name_or_path)
    if p.suffix.lower() != ".yaml" and p.suffix.lower() != ".yml":
        # treat as name within known config locations (new standardized first, then legacy)
        root = Path(__file__).resolve().parents[1]
        candidates = [
            root / "configs" / "aurora" / f"{name_or_path}.yaml",
            root / "configs" / f"{name_or_path}.yaml",
            root / "configs" / "runner" / f"{name_or_path}.yaml",
            root / "skalp_bot" / "configs" / f"{name_or_path}.yaml",
        ]
    else:
        candidates = [p if p.is_absolute() else Path.cwd() / p]
    for c in candidates:
        try:
            if c.exists():
                return c
        except Exception:
            continue
    return None


def load_config_any(name_or_path: str | None) -> dict:
    """Load YAML config from resolved path. Returns {} if not found or invalid."""
    p = resolve_config_path(name_or_path)
    if p is None:
        return {}
    try:
        with p.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                return {}
            return data
    except Exception:
        return {}


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


# --- Unified precedence + env overrides ---

def load_config_precedence(default_candidates: list[str] | None = None) -> dict:
    """Load config with precedence:

    1) Env AURORA_CONFIG (absolute/relative path or bare name)
    2) Env AURORA_CONFIG_NAME (bare name)
    3) First existing file from default_candidates list

    Bare names are resolved via resolve_config_path().
    If nothing found, returns {}.
    """
    # 1) Explicit env
    env_path = os.getenv('AURORA_CONFIG') or os.getenv('AURORA_CONFIG_NAME')
    if env_path:
        data = load_config_any(env_path)
        if data:
            return data
    # 2) Defaults chain
    candidates = default_candidates or [
        # standardized aurora templates first
        'configs/aurora/base.yaml',
        'configs/aurora/prod.yaml',
        'configs/aurora/testnet.yaml',
        # legacy chain
        'configs/master_config_v2.yaml',
        'configs/master_config_v1.yaml',
        'configs/aurora_config.template.yaml',
        'skalp_bot/configs/default.yaml',
    ]
    root = Path(__file__).resolve().parents[1]
    for rel in candidates:
        try:
            p = Path(rel)
            if not p.is_absolute():
                p = root / p
            if p.exists():
                return load_config(p)
        except Exception:
            continue
    return {}


def _set_nested(cfg: dict, dotted_key: str, value) -> None:
    cur = cfg
    parts = dotted_key.split('.')
    for i, k in enumerate(parts):
        last = i == len(parts) - 1
        if last:
            cur[k] = value
        else:
            if k not in cur or not isinstance(cur[k], dict):
                cur[k] = {}
            cur = cur[k]


def apply_env_overrides(cfg: dict) -> dict:
    """Apply environment variable overrides onto YAML config.

    Supports common keys across aurora/guards/risk/slippage/trap/pretrade/trading/security/api.
    """
    if not isinstance(cfg, dict):
        cfg = {}

    def _maybe(env: str, cast, key: str):
        v = os.getenv(env)
        if v is None:
            return
        try:
            _set_nested(cfg, key, cast(v))
        except Exception:
            pass

    # booleans
    as_bool = lambda x: str(x).strip().lower() in {'1', 'true', 'yes', 'on'}

    # aurora health/cooloff
    _maybe('AURORA_LATENCY_GUARD_MS', float, 'aurora.latency_guard_ms')
    _maybe('AURORA_LATENCY_WINDOW_SEC', int, 'aurora.latency_window_sec')
    _maybe('AURORA_COOLOFF_SEC', int, 'aurora.cooloff_base_sec')
    _maybe('AURORA_HALT_THRESHOLD_REPEATS', int, 'aurora.halt_threshold_repeats')

    # api + security
    _maybe('AURORA_API_HOST', str, 'api.host')
    _maybe('AURORA_API_PORT', int, 'api.port')
    _maybe('OPS_TOKEN', str, 'security.ops_token')
    _maybe('AURORA_OPS_TOKEN', str, 'security.ops_token')

    # guards
    _maybe('AURORA_SPREAD_BPS_LIMIT', float, 'guards.spread_bps_limit')
    _maybe('AURORA_LATENCY_MS_LIMIT', float, 'guards.latency_ms_limit')
    _maybe('AURORA_VOL_GUARD_STD_BPS', float, 'guards.vol_guard_std_bps')
    v = os.getenv('TRAP_GUARD')
    if v is not None:
        try:
            _set_nested(cfg, 'guards.trap_guard_enabled', as_bool(v))
        except Exception:
            pass

    # risk
    _maybe('AURORA_PI_MIN_BPS', float, 'risk.pi_min_bps')
    _maybe('AURORA_MAX_CONCURRENT', int, 'risk.max_concurrent')
    _maybe('AURORA_SIZE_SCALE', float, 'risk.size_scale')

    # slippage
    _maybe('AURORA_SLIP_ETA', float, 'slippage.eta_fraction_of_b')

    # pretrade
    _maybe('AURORA_ORDER_PROFILE', str, 'pretrade.order_profile')

    # trap
    _maybe('AURORA_TRAP_WINDOW_S', float, 'trap.window_s')
    _maybe('AURORA_TRAP_LEVELS', int, 'trap.levels')
    _maybe('AURORA_TRAP_Z_THRESHOLD', float, 'trap.z_threshold')
    _maybe('AURORA_TRAP_CANCEL_PCTL', int, 'trap.cancel_pctl')

    # trading
    _maybe('TRADING_MAX_LATENCY_MS', int, 'trading.max_latency_ms')

    return cfg
