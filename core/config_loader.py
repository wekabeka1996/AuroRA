from __future__ import annotations

from typing import Optional, Literal
import os
import sys
from pathlib import Path
from pydantic import BaseModel, Field, conint, confloat, ValidationError
from typing import Annotated
import yaml
from datetime import datetime, timezone


class RewardCfg(BaseModel):
    tp_pct: Annotated[float, confloat(ge=0, le=100)] = 0.5
    trail_bps: Annotated[int, conint(ge=0)] = 20
    trail_activate_at_R: Annotated[float, confloat(ge=0, le=5)] = 0.5
    breakeven_after_R: Annotated[float, confloat(ge=0, le=5)] = 0.8
    max_position_age_sec: Annotated[int, conint(ge=10)] = 3600
    atr_mult_sl: Annotated[float, confloat(ge=0, le=10)] = 1.2
    target_R: Annotated[float, confloat(ge=0, le=10)] = 1.0
    max_R: Annotated[float, confloat(ge=0, le=20)] = 3.0


class GatesCfg(BaseModel):
    spread_bps_limit: Annotated[int, conint(gt=0, lt=2000)] = 80
    latency_ms_limit: Annotated[int, conint(gt=0, lt=5000)] = 500
    vol_guard_std_bps: Annotated[int, conint(gt=0, lt=5000)] = 300
    daily_dd_limit_pct: Annotated[float, confloat(gt=0, le=50)] = 10.0
    cvar_alpha: Annotated[float, confloat(gt=0, lt=0.5)] = 0.1
    cvar_limit: Annotated[float, confloat(ge=0, le=100)] = 0.0
    reject_storm_pct: Annotated[float, confloat(ge=0, le=1)] = 0.5
    reject_storm_cooldown_s: Annotated[int, conint(ge=0, le=3600)] = 60
    no_trap_mode: bool = True


class DQCfg(BaseModel):
    enabled: bool = True
    cyclic_k: Annotated[int, conint(ge=2, le=20)] = 5
    cooldown_steps: Annotated[int, conint(ge=1, le=10000)] = 300


class Config(BaseModel):
    env: Literal['dev','testnet','prod'] = 'testnet'
    symbols: list[str] = ['BTCUSDT']
    reward: RewardCfg = Field(default_factory=RewardCfg)
    gates: GatesCfg = Field(default_factory=GatesCfg)
    dq: DQCfg = Field(default_factory=DQCfg)


def _health_error(msg: str) -> None:
    # Emit to stdout in a consistent way; api/service.py uses EventEmitter, but loader can run early.
    now = datetime.now(timezone.utc).isoformat()
    print(f"HEALTH.ERROR [{now}] {msg}", file=sys.stderr)


def _load_yaml(path: Path) -> dict:
    try:
        with path.open('r', encoding='utf-8') as f:
            data = yaml.safe_load(f) or {}
            if not isinstance(data, dict):
                raise ValueError("YAML root must be a mapping")
            return data
    except Exception as e:
        raise RuntimeError(f"Failed to load YAML '{path}': {e}")


def load_config(name: Optional[str]) -> Config:
    """Reads .env:AURORA_CONFIG_NAME or provided name, loads YAML into Config. On error, emit HEALTH.ERROR and exit(2)."""
    cfg_name = (name or os.getenv('AURORA_CONFIG_NAME') or '').strip()
    if not cfg_name:
        cfg_name = 'master_config_v1'
    # search in configs/
    root = Path(__file__).resolve().parents[1]
    yaml_path = root / 'configs' / f"{cfg_name}.yaml"
    try:
        raw = _load_yaml(yaml_path)
        cfg = Config(**raw)
        return cfg
    except (ValidationError, RuntimeError, Exception) as e:
        _health_error(f"CONFIG.LOAD_FAIL name={cfg_name} path={yaml_path}: {e}")
        sys.exit(2)
