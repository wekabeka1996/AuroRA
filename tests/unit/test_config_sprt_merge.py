import os
from common.config import load_sprt_cfg


def test_yaml_only_defaults():
    cfg = {"sprt": {"enabled": True, "sigma": 0.8, "A": 2.5, "B": -2.5, "max_obs": 8}}
    sc = load_sprt_cfg(cfg)
    assert (sc.enabled, sc.sigma, sc.A, sc.B, sc.max_obs) == (True, 0.8, 2.5, -2.5, 8)


def test_env_overrides_yaml(monkeypatch):
    cfg = {"sprt": {"enabled": False, "sigma": 0.8, "A": 2.5, "B": -2.5, "max_obs": 8}}
    monkeypatch.setenv("AURORA_SPRT_ENABLED", "true")
    monkeypatch.setenv("AURORA_SPRT_SIGMA", "1.2")
    monkeypatch.setenv("AURORA_SPRT_A", "3.0")
    monkeypatch.setenv("AURORA_SPRT_B", "-3.0")
    monkeypatch.setenv("AURORA_SPRT_MAX_OBS", "12")
    sc = load_sprt_cfg(cfg)
    assert (sc.enabled, sc.sigma, sc.A, sc.B, sc.max_obs) == (True, 1.2, 3.0, -3.0, 12)
