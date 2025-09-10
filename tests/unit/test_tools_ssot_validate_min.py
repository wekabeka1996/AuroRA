import json

from tools import ssot_validate


def test_validate_ok_sample(tmp_path):
    # create a minimal config that should pass top-level checks (but not full schema)
    cfg = {"name": "test", "risk": {"cvar": {"limit": 0.1}}, "timescale": {"ts_unit": "ms"}}
    p = tmp_path / "cfg.json"
    p.write_text(json.dumps(cfg))

    # run validator functions directly where possible
    # ensure that missing required fields trigger SystemExit when using CLI wrapper
    try:
        ssot_validate._check_unknown_top_level(cfg, ssot_validate.SCHEMA)
    except SystemExit as e:
        # unknown keys should not be present in this minimal cfg
        assert False, f"unexpected SystemExit: {e}"

import sys, subprocess, textwrap, tempfile, pathlib

def run_cfg(toml: str) -> int:
    with tempfile.NamedTemporaryFile('w', suffix='.toml', delete=False, encoding='utf-8') as f:
        f.write(textwrap.dedent(toml))
        p = pathlib.Path(f.name)
    r = subprocess.run([sys.executable, "tools/ssot_validate.py", "--config", str(p)])
    return r.returncode

def test_unknown_top_level():
    code = run_cfg("""
        [risk.cvar]
        limit = 0.95
        [sizing]
        default = "x"
        [execution.sla]
        max_latency_ms = 50
        foobar = 1  # топ-левел неизвестная секция
        [order_sink.sim_local]
        latency_ms = 5
        [timescale]
        ts_unit = "ns"
    """)
    assert code == 20

def test_nulls_profile():
    code = run_cfg("""
        [risk.cvar]
        limit = 0.95
        [sizing]
        default = "x"
        [execution.sla]
        max_latency_ms = 50
        profile = ""
        [order_sink.sim_local]
        latency_ms = 5
        [timescale]
        ts_unit = "ns"
    """)
    assert code == 30

def test_missing_required():
    code = run_cfg("""
        [risk.cvar]
        limit = 0.95
        [sizing]
        default = "x"
        [execution.sla]
        max_latency_ms = 50
        [order_sink.sim_local]
        latency_ms = 5
        # отсутствует timescale.ts_unit
    """)
    assert code == 50

def test_invariant_live_401():
    code = run_cfg("""
        [risk.cvar]
        limit = 0.95
        [sizing]
        default = "x"
        [execution.sla]
        max_latency_ms = 50
        [market_data]
        source = "live_x"
        [order_sink]
        mode = "net"
        [orders]
        enabled = true
        [timescale]
        ts_unit = "ns"
    """)
    assert code in (401, 402, 403)
