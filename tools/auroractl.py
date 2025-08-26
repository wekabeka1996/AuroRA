#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path
from typing import Optional

import typer

# Ensure repo root on sys.path for local runs
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.env import load_env
from core.config_loader import load_config as load_cfg_model


app = typer.Typer(add_completion=False, help="Aurora unified CLI")


def _exit(code: int, msg: str):
    typer.echo(msg)
    raise typer.Exit(code)


@app.callback()
def _load_env(dotenv: bool = typer.Option(True, help="Load .env from repo root")):
    env = load_env(dotenv=dotenv, path=ROOT / ".env")
    typer.echo(f"env loaded: mode={env.AURORA_MODE}, testnet={env.EXCHANGE_TESTNET}, dry_run={env.DRY_RUN}")


@app.command()
def start_api(port: int = typer.Option(8000), host: str = typer.Option("127.0.0.1")):
    """Start FastAPI with uvicorn, ensuring .env is loaded and port is free."""
    svc = ROOT / "api" / "service.py"
    if not svc.exists():
        _exit(2, "api/service.py not found")

    # If port already has a healthy instance, do not start another
    try:
        import requests
        r = requests.get(f"http://{host}:{port}/health", timeout=1.5)
        if r.status_code == 200:
            _exit(0, f"API already running at http://{host}:{port}")
    except Exception:
        pass

    # On Windows, attempt to free port by killing existing process bound to it
    if sys.platform.startswith("win"):
        try:
            out = subprocess.check_output(["netstat", "-ano"], creationflags=0x08000000).decode(errors='ignore')
            pids = []
            for line in out.splitlines():
                if f":{port} " in line and "LISTENING" in line.upper():
                    parts = line.split()
                    if parts:
                        pids.append(parts[-1])
            for pid in set(pids):
                try:
                    subprocess.call(["taskkill", "/PID", pid, "/F", "/T"], creationflags=0x08000000)
                except Exception:
                    pass
        except Exception:
            pass

    # Start uvicorn with --env-file to ensure environment
    cmd = [
        sys.executable,
        "-m",
        "uvicorn",
        "api.service:app",
        "--host",
        host,
        "--port",
        str(port),
        "--env-file",
        str(ROOT / ".env"),
        "--log-level",
        "info",
    ]
    subprocess.Popen(cmd, cwd=str(ROOT))

    # quick health probe loop (liveness is 200 even while models load)
    import requests
    ops_token = os.getenv("AURORA_OPS_TOKEN") or os.getenv("OPS_TOKEN")
    headers = {"X-OPS-TOKEN": ops_token} if ops_token else {}
    for i in range(20):
        try:
            r = requests.get(f"http://{host}:{port}/liveness", headers=headers, timeout=2)
            if r.status_code == 200:
                typer.echo(f"API started at http://{host}:{port}")
                raise typer.Exit(0)
            # Fallback: if liveness is protected and no token, check public /health
            if r.status_code in (401, 403) and not headers:
                r2 = requests.get(f"http://{host}:{port}/health", timeout=2)
                if r2.status_code == 200:
                    typer.echo(f"API started (health) at http://{host}:{port}")
                    raise typer.Exit(0)
        except Exception:
            pass
        time.sleep(0.75)
    typer.echo("API start attempted; liveness not responding yet")
    raise typer.Exit(1)


@app.command()
def config_use(name: str = typer.Option(..., "--name", help="Config name without .yaml, e.g. master_config_v2")):
    """Set AURORA_CONFIG_NAME in .env to the given config name (idempotent)."""
    env_path = ROOT / ".env"
    env_lines = []
    if env_path.exists():
        env_lines = env_path.read_text(encoding="utf-8").splitlines()
    found = False
    for i, line in enumerate(env_lines):
        if line.startswith("AURORA_CONFIG_NAME="):
            env_lines[i] = f"AURORA_CONFIG_NAME={name}"
            found = True
            break
    if not found:
        env_lines.append(f"AURORA_CONFIG_NAME={name}")
    env_path.write_text("\n".join(env_lines) + "\n", encoding="utf-8")
    typer.echo(f"AURORA_CONFIG_NAME set to '{name}' in .env")


@app.command()
def config_validate(name: Optional[str] = typer.Option(None, "--name", help="Override name; defaults to .env:AURORA_CONFIG_NAME")):
    """Validate YAML config against schema and print normalized JSON."""
    try:
        cfg = load_cfg_model(name)
        typer.echo(json.dumps(cfg.model_dump(), ensure_ascii=False, indent=2))
        return
    except Exception as e:
        typer.echo(f"validation failed: {e}")
        raise typer.Exit(2)


@app.command()
def stop_api(port: int = typer.Option(8000)):
    """Stop uvicorn/api process listening on port (best-effort)."""
    try:
        killed = 0
        if sys.platform.startswith("win"):
            # Try by port first
            try:
                out = subprocess.check_output(["netstat", "-ano"], creationflags=0x08000000).decode(errors='ignore')
                pids = []
                for line in out.splitlines():
                    if f":{port} " in line and "LISTENING" in line.upper():
                        parts = line.split()
                        if parts:
                            pids.append(parts[-1])
                for pid in set(pids):
                    try:
                        subprocess.call(["taskkill", "/PID", pid, "/F", "/T"], creationflags=0x08000000)
                        killed += 1
                    except Exception:
                        pass
            except Exception:
                pass
            # Fallback by command line match
            if killed == 0:
                try:
                    out = subprocess.check_output(["wmic", "process", "where", "(Name='python.exe')", "get", "ProcessId,CommandLine"], creationflags=0x08000000)
                    import re
                    for line in out.decode(errors='ignore').splitlines():
                        if "api.service:app" in line or "api\\service.py" in line or "api/service.py" in line:
                            m = re.search(r"(\d+)\s*$", line)
                            if m:
                                pid = m.group(1)
                                subprocess.call(["taskkill", "/PID", pid, "/F", "/T"], creationflags=0x08000000)
                                killed += 1
                except Exception:
                    pass
        else:
            # Unix-like
            try:
                subprocess.call(["pkill", "-f", "api.service:app"])  # best-effort
                killed = 1
            except Exception:
                pass
        # Be idempotent: return success even if nothing was found to kill
        _exit(0, "Stopped" if killed else "No api process found")
    except Exception as e:
        _exit(1, f"stop failed: {e}")


@app.command()
def health(port: int = 8000, endpoint: str = typer.Option("health", help="health|liveness|readiness"), ops_token: Optional[str] = typer.Option(None, help="OPS token for protected endpoints")):
    """HTTP GET health-like probe."""
    import requests
    ep = endpoint.strip("/")
    headers = {}
    token = ops_token or os.getenv("AURORA_OPS_TOKEN") or os.getenv("OPS_TOKEN")
    if ep in {"liveness", "readiness"} and token:
        headers["X-OPS-TOKEN"] = token
    try:
        r = requests.get(f"http://127.0.0.1:{port}/{ep}", headers=headers, timeout=3)
        if r.status_code == 200:
            typer.echo(f"API {ep} OK on port {port}")
            raise typer.Exit(0)
        typer.echo(f"API {ep} not OK: {r.status_code}")
        raise typer.Exit(1)
    except typer.Exit:
        raise
    except Exception as e:
        typer.echo(f"API {ep} check failed: {e}")
        raise typer.Exit(1)


@app.command()
def canary(minutes: int = typer.Option(60, help="Duration in minutes")):
    """Run canary harness for N minutes."""
    mod = ROOT / "tools" / "run_canary.py"
    if not mod.exists():
        _exit(2, "tools/run_canary.py not found")
    cmd = [sys.executable, str(mod), "--minutes", str(minutes)]
    rc = subprocess.call(cmd, cwd=str(ROOT))
    _exit(rc, f"canary completed rc={rc}")


@app.command()
def smoke(public_only: bool = typer.Option(False, help="Only public endpoints")):
    """Quick Binance smoke test (public and/or private)."""
    mod = ROOT / "tools" / "binance_smoke.py"
    if not mod.exists():
        _exit(0, "no smoke harness found; skipping")
    args = [sys.executable, str(mod)]
    if public_only:
        args.append("--public-only")
    rc = subprocess.call(args, cwd=str(ROOT))
    _exit(rc, "smoke done")


@app.command()
def testnet(minutes: int = typer.Option(5), preflight: bool = typer.Option(True)):
    """Run short testnet cycle (merged run_live_testnet + smoke)."""
    mod = ROOT / "tools" / "run_live_testnet.py"
    if not mod.exists():
        _exit(2, "tools/run_live_testnet.py not found")
    args = [sys.executable, str(mod), "--minutes", str(minutes), "--load-dotenv"]
    if preflight:
        args.append("--preflight")
    rc = subprocess.call(args, cwd=str(ROOT))
    _exit(rc, f"testnet completed rc={rc}")


@app.command()
def wallet_check():
    """Check exchange keys/balances and save report to artifacts/wallet_check.json."""
    env = load_env(dotenv=False)
    missing = []
    if not env.DRY_RUN:
        if not env.BINANCE_API_KEY:
            missing.append("BINANCE_API_KEY")
        if not env.BINANCE_API_SECRET:
            missing.append("BINANCE_API_SECRET")
    if missing:
        _exit(2, "Missing keys: " + ", ".join(missing))

    try:
        import ccxt  # type: ignore
        ex_id = env.EXCHANGE_ID or "binanceusdm"
        klass = getattr(ccxt, ex_id)
        exchange = klass({
            "apiKey": env.BINANCE_API_KEY,
            "secret": env.BINANCE_API_SECRET,
            "enableRateLimit": True,
            "options": {"defaultType": "future" if env.EXCHANGE_USE_FUTURES else "spot"},
            "timeout": 10000,
            "recvWindow": env.BINANCE_RECV_WINDOW,
        })
        if hasattr(exchange, 'set_sandbox_mode'):
            exchange.set_sandbox_mode(env.EXCHANGE_TESTNET)

        bal = exchange.fetch_balance(params={})
        if isinstance(bal, dict):
            positions = bal.get('info', {}).get('positions')
            usdt = bal.get('USDT') or {}
        else:
            positions = None
            usdt = {}

        def _num(x):
            try:
                return float(x)
            except Exception:
                return None

        usdt_free = _num(usdt.get('free'))
        usdt_used = _num(usdt.get('used'))
        usdt_total = _num(usdt.get('total'))

        withdrawals_checked = False
        usdt_withdrawals_enabled = None
        usdt_withdraw_min = None
        usdt_withdraw_fee_est = None
        if not env.EXCHANGE_TESTNET and not env.DRY_RUN:
            try:
                if hasattr(exchange, 'load_markets'):
                    exchange.load_markets()
                currencies = exchange.fetch_currencies() if (getattr(exchange, 'has', {}).get('fetchCurrencies', False) or hasattr(exchange, 'fetch_currencies')) else None
                cur = currencies.get('USDT') if isinstance(currencies, dict) else None
                if cur:
                    info = cur.get('info') or {}
                    nets = info.get('networkList') or info.get('networks') or []
                    if isinstance(nets, list) and nets:
                        enabled_any = False
                        mins = []
                        fees = []
                        for n in nets:
                            we = n.get('withdrawEnable')
                            if isinstance(we, str):
                                we = we.lower() == 'true'
                            enabled_any = enabled_any or bool(we)
                            try:
                                if n.get('withdrawMin') is not None:
                                    mins.append(float(n['withdrawMin']))
                            except Exception:
                                pass
                            try:
                                if n.get('withdrawFee') is not None:
                                    fees.append(float(n['withdrawFee']))
                            except Exception:
                                pass
                        usdt_withdrawals_enabled = enabled_any
                        usdt_withdraw_min = min(mins) if mins else None
                        usdt_withdraw_fee_est = min(fees) if fees else None
                    else:
                        val = cur.get('withdraw')
                        usdt_withdrawals_enabled = bool(val) if isinstance(val, bool) else None
                withdrawals_checked = True
            except Exception:
                withdrawals_checked = False

        report = {
            "mode": env.AURORA_MODE,
            "testnet": env.EXCHANGE_TESTNET,
            "dry_run": env.DRY_RUN,
            "usdt": {"free": usdt_free, "used": usdt_used, "total": usdt_total},
            "positions_len": len(positions) if positions else 0,
            "withdrawals": {
                "checked": withdrawals_checked,
                "usdt_enabled": usdt_withdrawals_enabled,
                "usdt_min": usdt_withdraw_min,
                "usdt_fee_est": usdt_withdraw_fee_est,
            },
        }
        out = ROOT / "artifacts" / "wallet_check.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

        if not env.EXCHANGE_TESTNET and not env.DRY_RUN:
            if usdt_total is None or usdt_total <= 0.0:
                _exit(3, f"wallet insufficient balance; saved {out}")
            if withdrawals_checked and usdt_withdrawals_enabled is False:
                _exit(4, f"withdrawals disabled for USDT; saved {out}")

        _exit(0, f"wallet OK: saved {out}")
    except typer.Exit:
        # propagate intended exit codes from _exit
        raise
    except Exception as e:
        _exit(1, f"wallet check failed: {e}")


@app.command()
def metrics(window: str = typer.Option("3600", "--window-sec", help="Window in seconds or arithmetic expression, e.g. 720*60"),
            window_sec: Optional[str] = typer.Option(None, help="compat alias for --window-sec")):
    """Aggregate events.jsonl into summary JSON and artifacts."""
    # parse window as int or arithmetic expression (digits + +-*/())
    def _parse_sec(expr: str) -> int:
        try:
            return int(expr)
        except Exception:
            import re
            if not re.fullmatch(r"[0-9\+\-\*/\(\)\s]+", expr or ""):
                _exit(2, f"invalid --window-sec expression: {expr}")
            try:
                val = eval(expr, {"__builtins__": None}, {})
                sec = int(val)
                return sec
            except Exception:
                _exit(2, f"failed to evaluate --window-sec: {expr}")
            # satisfies type checker; unreachable due to _exit above
            return 0

    # Prefer explicit window_sec if provided (tests call metrics(window_sec=...))
    if window_sec is not None:
        window_val = window_sec
    else:
        window_val = window
    parsed_window_sec = _parse_sec(window_val)
    # Prefer session dir aurora_events.jsonl, then logs/aurora_events.jsonl, then legacy logs/events.jsonl
    sess = os.getenv("AURORA_SESSION_DIR")
    if sess:
        events = Path(sess) / "aurora_events.jsonl"
    else:
        events = ROOT / "logs" / "aurora_events.jsonl"
    if not events.exists():
        legacy = ROOT / "logs" / "events.jsonl"
        if legacy.exists():
            events = legacy
        else:
            _exit(1, f"events file not found in session or logs: {events} / {legacy}")
    # lightweight inline parser to avoid new deps
    import time
    now = time.time()
    cutoff = now - parsed_window_sec
    recs = []
    latency_points = []  # (ts_ms, p95_ms)
    for line in events.read_text(encoding="utf-8").splitlines():
        try:
            obj = json.loads(line)
            # allow if payload has ts, else include
            ts = None
            p = obj.get('payload') or {}
            ts = p.get('ts') or p.get('ts_server')
            if ts is not None:
                tsec = float(ts) / (1000.0 if ts and ts > 1e12 else 1.0)
                if tsec < cutoff:
                    continue
            # latency extraction for timeseries
            v = None
            for key in ('latency_p95_ms', 'p95_ms', 'latency_ms'):
                val = p.get(key)
                if val is not None:
                    try:
                        v = float(val)
                        break
                    except Exception:
                        v = None
            if ts is not None and v is not None:
                ts_ms = int(float(ts) if float(ts) > 1e12 else float(ts) * 1000.0)
                latency_points.append((ts_ms, v))
            recs.append(obj)
        except Exception:
            continue

    # compute some trivial metrics
    expected_accepts = sum(1 for r in recs if r.get('code') == 'AURORA.EXPECTED_RETURN_ACCEPT')
    latency_high = sum(1 for r in recs if r.get('code') == 'HEALTH.LATENCY_P95_HIGH')
    spread_trips = sum(1 for r in recs if 'spread' in (r.get('type') or '').lower())
    risk_denies = sum(1 for r in recs if r.get('type') == 'RISK.DENY')

    summary = {
        "result": "OK" if latency_high == 0 and risk_denies == 0 else "ATTN",
        "violations": [
            *( ["latency_p95_high"] if latency_high else [] ),
            *( ["risk_denies"] if risk_denies else [] ),
        ],
    "params": {"window_sec": parsed_window_sec},
        "computed": {
            "expected_return_accepts": expected_accepts,
            "latency_p95_alerts": latency_high,
            "spread_trips": spread_trips,
            "risk_denies": risk_denies,
        },
        "timestamp": int(now),
    }

    rep_dir = ROOT / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    (rep_dir / "summary_gate_status.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    artifacts = ROOT / "artifacts"
    artifacts.mkdir(parents=True, exist_ok=True)
    (artifacts / "canary_summary.md").write_text(f"# Canary summary\n\nWindow: {parsed_window_sec}s\n\n" + json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    # write timeseries CSV (epoch_ms,p95_ms)
    csv_lines = ["ts,value"]
    # Sort by timestamp ascending
    latency_points.sort(key=lambda x: x[0])
    for ts_ms, v in latency_points:
        csv_lines.append(f"{ts_ms},{v}")
    (artifacts / "latency_p95_timeseries.csv").write_text("\n".join(csv_lines) + "\n", encoding="utf-8")

    # optional pushgateway
    try:
        push_url = os.getenv("PUSHGATEWAY_URL")
        if push_url:
            import requests
            # Prepare minimal Prometheus exposition text
            ok = 1 if summary["result"] == "OK" else 0
            text = []
            text.append(f"aurora_gate_ok {ok}")
            c = summary["computed"]
            text.append(f"aurora_expected_return_accepts {c.get('expected_return_accepts', 0)}")
            text.append(f"aurora_latency_p95_alerts {c.get('latency_p95_alerts', 0)}")
            text.append(f"aurora_risk_denies {c.get('risk_denies', 0)}")
            # Post to a default job; ignore errors
            requests.post(push_url.rstrip('/') + "/metrics/job/aurora_cli", data="\n".join(text), timeout=3)
    except Exception:
        pass

    _exit(0 if summary["result"] == "OK" else 1, f"metrics done: {summary['result']}")


@app.command()
def disarm(ops_token: Optional[str] = typer.Option(None)):
    """POST to /aurora/disarm."""
    import requests
    token = ops_token or os.getenv("AURORA_OPS_TOKEN")
    if not token:
        _exit(2, "OPS token required (AURORA_OPS_TOKEN)")
    r = requests.post("http://127.0.0.1:8000/aurora/disarm", headers={"X-OPS-TOKEN": token}, timeout=5)
    _exit(0 if r.ok else 1, f"disarm: {r.status_code}")


@app.command()
def cooloff(sec: int = typer.Option(120), ops_token: Optional[str] = typer.Option(None)):
    """POST to /ops/cooloff/{sec}."""
    import requests
    token = ops_token or os.getenv("AURORA_OPS_TOKEN")
    if not token:
        _exit(2, "OPS token required (AURORA_OPS_TOKEN)")
    r = requests.post(f"http://127.0.0.1:8000/ops/cooloff/{sec}", headers={"X-OPS-TOKEN": token}, timeout=5)
    _exit(0 if r.ok else 1, f"cooloff: {r.status_code}")


@app.command()
def one_click(
    mode: str = typer.Option("testnet", help="testnet or live"),
    minutes: int = typer.Option(15, help="Duration for the run"),
    preflight: bool = typer.Option(True, help="Run smoke/preflight before canary"),
    analytics: bool = typer.Option(False, help="Attempt to start monitoring stack (docker compose)"),
):
    """Run wallet-check → start API → wait healthy → canary → metrics → stop API."""
    mode_l = str(mode).lower().strip()
    if mode_l not in {"testnet", "live"}:
        _exit(2, "mode must be 'testnet' or 'live'")

    # Prepare environment for the run (do not overwrite explicit user overrides)
    if mode_l == "testnet":
        os.environ.setdefault("EXCHANGE_TESTNET", "true")
        # Prefer shadow mode for testnet to avoid hard health gating on unloaded models
        os.environ.setdefault("AURORA_MODE", "shadow")
        os.environ.setdefault("DRY_RUN", "false")
    else:
        os.environ["EXCHANGE_TESTNET"] = "false"
        os.environ.setdefault("AURORA_MODE", "prod")
        os.environ.setdefault("DRY_RUN", "false")

    # 1) Wallet check
    rc = subprocess.call([sys.executable, str(ROOT / "tools" / "auroractl.py"), "wallet-check"], cwd=str(ROOT))
    if rc != 0:
        _exit(rc, f"wallet-check failed rc={rc}")

    # 2) Optionally bring up monitoring (Prom/Grafana) via docker compose
    if analytics and (ROOT / "docker-compose.yml").exists():
        try:
            subprocess.call(["docker", "compose", "up", "-d", "--build"], cwd=str(ROOT))
        except Exception:
            typer.echo("monitoring startup skipped (docker not available)")

    # 3) Start API
    subprocess.call([sys.executable, str(ROOT / "tools" / "auroractl.py"), "start-api"], cwd=str(ROOT))

    # 4) Wait for health (best-effort)
    healthy = False
    for _ in range(30):
        rc_h = subprocess.call([sys.executable, str(ROOT / "tools" / "auroractl.py"), "health"], cwd=str(ROOT))
        if rc_h == 0:
            healthy = True
            break
        time.sleep(1.0)
    typer.echo(f"health: {'OK' if healthy else 'not ready'}")

    # 5) Run canary / testnet
    try:
        if mode_l == "testnet":
            args = [sys.executable, str(ROOT / "tools" / "run_live_testnet.py"), "--minutes", str(minutes)]
            if preflight:
                args.append("--preflight")
            rc_run = subprocess.call(args, cwd=str(ROOT))
        else:
            # live: directly run canary harness
            rc_run = subprocess.call([sys.executable, str(ROOT / "tools" / "run_canary.py"), "--minutes", str(minutes)], cwd=str(ROOT))
    except KeyboardInterrupt:
        rc_run = 130

    # 6) Aggregate metrics for the run window
    try:
        rc_m = subprocess.call([sys.executable, str(ROOT / "tools" / "auroractl.py"), "metrics", "--window-sec", f"{minutes}*60"], cwd=str(ROOT))
    except Exception:
        rc_m = 1

    # 7) Stop API
    try:
        subprocess.call([sys.executable, str(ROOT / "tools" / "auroractl.py"), "stop-api"], cwd=str(ROOT))
    except Exception:
        pass

    final_rc = rc_run if rc_run != 0 else rc_m
    _exit(final_rc, f"one-click done: canary_rc={rc_run} metrics_rc={rc_m}")

def main():
    app()


if __name__ == "__main__":
    main()
