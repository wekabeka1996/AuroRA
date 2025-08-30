import json
from pathlib import Path

import pytest

from core.config.loader import ConfigManager, ConfigError, HotReloadViolation


# -------------------- Helpers --------------------

def _w(p: Path, txt: str) -> None:
    p.write_text(txt, encoding="utf-8")


def _schema_min() -> dict:
    return {
        "$id": "aurora.schema/v1",
        "hotReloadWhitelist": ["risk.cvar.limit"],
        "schema": {
            "type": "object",
            "properties": {
                "risk": {
                    "type": "object",
                    "properties": {
                        "cvar": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": "number", "minimum": 0, "default": 0.02},
                                "alpha": {"type": "number", "minimum": 0.80, "maximum": 0.999, "default": 0.95},
                            },
                            "required": ["limit"],
                        }
                    },
                    "required": ["cvar"],
                },
                "execution": {
                    "type": "object",
                    "properties": {
                        "sla": {
                            "type": "object",
                            "properties": {
                                "max_latency_ms": {"type": "integer", "minimum": 0, "default": 25}
                            },
                            "required": ["max_latency_ms"],
                        }
                    },
                    "required": ["sla"],
                },
                "hotreload": {
                    "type": "object",
                    "properties": {"whitelist": {"type": "array", "items": {"type": "string"}}},
                },
            },
            "required": ["risk", "execution"],
            "additionalProperties": True,
        },
    }


# -------------------- Tests --------------------


def test_load_env_override_and_schema_defaults(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "default.toml"
    sch = tmp_path / "schema.json"

    _w(
        cfg,
        """
[risk.cvar]
limit = 0.02

[execution.sla]
max_latency_ms = 25

[hotreload]
whitelist = ["execution.sla.max_latency_ms"]
""",
    )
    sch.write_text(json.dumps(_schema_min()), encoding="utf-8")

    # ENV override: raise SLA latency from 25 -> 30
    monkeypatch.setenv("AURORA_CONFIG", str(cfg))
    monkeypatch.setenv("AURORA__EXECUTION__SLA__MAX_LATENCY_MS", "30")

    mgr = ConfigManager(schema_path=sch, enable_watcher=False)
    c = mgr.config

    # defaults applied and env override visible
    assert c.get("risk.cvar.limit") == 0.02
    assert c.get("risk.cvar.alpha") == 0.95  # from defaults
    assert c.get("execution.sla.max_latency_ms") == 30  # ENV override

    # schema version is propagated
    assert c.schema_version == "aurora.schema/v1"


def test_validation_error_propagates(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "bad.toml"
    sch = tmp_path / "schema.json"

    _w(
        cfg,
        """
[risk.cvar]
limit = "oops"

[execution.sla]
max_latency_ms = 25
""",
    )
    sch.write_text(json.dumps(_schema_min()), encoding="utf-8")
    monkeypatch.setenv("AURORA_CONFIG", str(cfg))

    with pytest.raises(ConfigError):
        ConfigManager(schema_path=sch)


def test_hot_reload_whitelist_allows_and_blocks(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "default.toml"
    sch = tmp_path / "schema.json"

    _w(
        cfg,
        """
[risk.cvar]
limit = 0.02
alpha = 0.95

[execution.sla]
max_latency_ms = 25

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    sch.write_text(json.dumps(_schema_min()), encoding="utf-8")
    monkeypatch.setenv("AURORA_CONFIG", str(cfg))

    mgr = ConfigManager(schema_path=sch, enable_watcher=False)

    # 1) Allowed change (whitelisted)
    _w(
        cfg,
        """
[risk.cvar]
limit = 0.03
alpha = 0.95

[execution.sla]
max_latency_ms = 25

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    changed = mgr.try_reload()
    assert changed is not None and "risk.cvar.limit" in changed

    # 2) Blocked change (not whitelisted)
    _w(
        cfg,
        """
[risk.cvar]
limit = 0.03
alpha = 0.95

[execution.sla]
max_latency_ms = 50  # change not in whitelist

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    with pytest.raises(HotReloadViolation):
        mgr.try_reload()


def test_config_hash_determinism_and_noop_reload(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "default.toml"
    sch = tmp_path / "schema.json"

    _w(
        cfg,
        """
[risk.cvar]
alpha = 0.95
limit = 0.02

[execution.sla]
max_latency_ms = 25

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    sch.write_text(json.dumps(_schema_min()), encoding="utf-8")
    monkeypatch.setenv("AURORA_CONFIG", str(cfg))

    mgr = ConfigManager(schema_path=sch, enable_watcher=False)
    h1 = mgr.config.config_hash

    # Rewrite with reordered keys/whitespace but same values
    _w(
        cfg,
        """
[execution.sla]
max_latency_ms = 25

[risk.cvar]
limit = 0.02
alpha = 0.95

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    changed = mgr.try_reload()
    h2 = mgr.config.config_hash

    # Hash deterministic and no functional changes -> changed can be empty set
    assert h1 == h2
    assert changed == set() or changed is None  # acceptable if mtime equal or parser preserves order


def test_reload_callback_invoked(tmp_path: Path, monkeypatch):
    cfg = tmp_path / "default.toml"
    sch = tmp_path / "schema.json"

    _w(
        cfg,
        """
[risk.cvar]
limit = 0.02

[execution.sla]
max_latency_ms = 25

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    sch.write_text(json.dumps(_schema_min()), encoding="utf-8")
    monkeypatch.setenv("AURORA_CONFIG", str(cfg))

    mgr = ConfigManager(schema_path=sch, enable_watcher=False)

    bucket = {}

    def cb(c, changed):
        bucket["called"] = True
        bucket["changed"] = changed
        bucket["hash"] = c.config_hash

    mgr.register_callback(cb)

    _w(
        cfg,
        """
[risk.cvar]
limit = 0.03

[execution.sla]
max_latency_ms = 25

[hotreload]
whitelist = ["risk.cvar.limit"]
""",
    )
    changed = mgr.try_reload()
    assert bucket.get("called") is True
    assert bucket.get("changed") == changed
    assert isinstance(bucket.get("hash"), str)


def test_missing_config_file_raises(tmp_path: Path):
    missing = tmp_path / "nope.toml"
    schema = tmp_path / "schema.json"
    schema.write_text(json.dumps(_schema_min()), encoding="utf-8")

    with pytest.raises(ConfigError):
        ConfigManager(config_path=missing, schema_path=schema)
