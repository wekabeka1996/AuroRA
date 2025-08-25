#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import sys
import time
import json
import signal
import subprocess
from pathlib import Path
from typing import Optional

try:
    import requests
except Exception:
    requests = None  # health-checks will be skipped if requests missing

ROOT = Path(__file__).resolve().parent.parent
EVENTS_PATH = ROOT / 'logs' / 'events.jsonl'
ARTIFACTS_DIR = ROOT / 'artifacts'
REPORTS_DIR = ROOT / 'reports'
TOOLS_DIR = ROOT / 'tools'


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        ln = raw.strip()
        if not ln or ln.startswith('#'):
            continue
        if '=' not in ln:
            continue
        name, val = ln.split('=', 1)
        name = name.strip()
        val = val.strip().strip('\"').strip("'")
        # strip inline comments starting with space + '#'
        import re as _re
        val = _re.split(r"\s+#", val, maxsplit=1)[0].strip()
        if name and (name not in os.environ or not os.environ.get(name)):
            os.environ[name] = val


def sanitize_env_value(name: str) -> None:
    val = os.getenv(name)
    if val is None:
        return
    clean = val.strip().strip('"').strip("'")
    import re as _re
    clean = _re.split(r"\s+#", clean, maxsplit=1)[0].strip()
    os.environ[name] = clean


def is_live_mode() -> bool:
    mode = (os.getenv('AURORA_MODE') or '').lower()
    dry = (os.getenv('DRY_RUN') or '').lower()
    return mode == 'prod' and dry in {'false', '0', 'no'}


def start_api(host: str, port: int) -> subprocess.Popen:
    # Start uvicorn: api.service:app
    cmd = [sys.executable, '-m', 'uvicorn', 'api.service:app', '--host', host, '--port', str(port)]
    proc = subprocess.Popen(cmd, cwd=str(ROOT), stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    return proc


def stop_proc(proc: Optional[subprocess.Popen]) -> None:
    if not proc:
        return
    try:
        if proc.poll() is None:
            if os.name == 'nt':
                proc.terminate()
            else:
                os.killpg(os.getpgid(proc.pid), signal.SIGTERM)
            try:
                proc.wait(timeout=10)
            except Exception:
                proc.kill()
    except Exception:
        pass


def health_check(base_url: str, allow_503_shadow: bool = True, timeout_sec: int = 30) -> bool:
    if requests is None:
        return True
    t0 = time.time()
    while time.time() - t0 < timeout_sec:
        try:
            r = requests.get(f'{base_url}/health', timeout=3)
            if r.status_code == 200:
                return True
            if allow_503_shadow and r.status_code == 503:
                # acceptable in shadow/uninitialized trading system
                return True
        except Exception:
            pass
        time.sleep(1.0)
    return False


def run_canary_harness(base_url: str, ops_token: Optional[str], minutes: int) -> int:
    script = TOOLS_DIR / 'canary_harness.py'
    if not script.exists():
        return 0
    args = [sys.executable, str(script), '--duration-min', str(minutes), '--window-sec', '300', '--base-url', base_url]
    if ops_token and ops_token.strip():
        args += ['--ops-token', ops_token.strip()]
    proc = subprocess.run(args, cwd=str(ROOT))
    return proc.returncode or 0


def run_shadow_traffic(base_url: str, minutes: int, rps: float) -> int:
    script = TOOLS_DIR / 'smoke_traffic.py'
    if not script.exists():
        return 0
    args = [sys.executable, str(script), '--base-url', base_url, '--duration-min', str(minutes), '--rps', str(rps)]
    return subprocess.run(args, cwd=str(ROOT)).returncode or 0


def start_live_runner(config_path: str) -> subprocess.Popen:
    # python -m skalp_bot.scripts.run_live_aurora <config>
    args = [sys.executable, '-m', 'skalp_bot.scripts.run_live_aurora', config_path]
    proc = subprocess.Popen(args, cwd=str(ROOT))
    return proc


def build_summary(minutes: int) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    summary_md = ARTIFACTS_DIR / f'canary_{minutes}min_summary.md'
    args = [
        sys.executable,
        str(TOOLS_DIR / 'canary_summary.py'),
        '--events', str(EVENTS_PATH),
        '--out-md', str(summary_md),
        '--out-ts', str(REPORTS_DIR / 'latency_p95_timeseries.csv'),
        '--out-flow', str(REPORTS_DIR / 'escalations_flow.md'),
    ]
    subprocess.run(args, cwd=str(ROOT), check=False)
    return summary_md


def run_gate(summary_md: Path, time_window_last: int = 300, strict: bool = True) -> int:
    status_out = REPORTS_DIR / 'summary_gate_status.json'
    args = [
        sys.executable,
        str(TOOLS_DIR / 'summary_gate.py'),
        '--summary', str(summary_md),
        '--events', str(EVENTS_PATH),
        '--time-window-last', str(time_window_last),
        '--status-out', str(status_out),
    ]
    if strict:
        args.insert(2, '--strict')
    proc = subprocess.run(args, cwd=str(ROOT))
    return proc.returncode or 0


def print_metrics_line() -> None:
    status_path = REPORTS_DIR / 'summary_gate_status.json'
    try:
        data = json.loads(status_path.read_text(encoding='utf-8'))
        c = data.get('computed', {})
        line = (
            f"latency_p95_ms={c.get('latency_p95_ms')}; "
            f"slip_ratio={c.get('slip_ratio')}; "
            f"expected_return_accepts={c.get('expected_return_accepts')}; "
            f"risk_denies={c.get('risk_denies')}; "
            f"slippage_guard_trips={c.get('slippage_guard_trips')}"
        )
        print(line)
    except Exception:
        pass


def tail_risk_health(n: int = 10) -> None:
    if not EVENTS_PATH.exists():
        return
    try:
        lines = EVENTS_PATH.read_text(encoding='utf-8').splitlines()[-5000:]
        selected = []
        for ln in lines:
            try:
                ev = json.loads(ln)
                t = str(ev.get('type') or '')
                if t.startswith('RISK.') or t.startswith('HEALTH.') or t.startswith('AURORA.HEALTH') or t.startswith('AURORA.RISK'):
                    selected.append(ln)
            except Exception:
                # fallback substring match
                if '"type"' in ln and ('RISK.' in ln or 'HEALTH.' in ln):
                    selected.append(ln)
        for ln in selected[-n:]:
            print(ln)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=int, default=60)
    ap.add_argument('--host', default='127.0.0.1')
    ap.add_argument('--port', type=int, default=8000)
    ap.add_argument('--runner-config', default='skalp_bot\\configs\\default.yaml')
    ap.add_argument('--rps', type=float, default=5.0)
    ap.add_argument('--time-window-last', type=int, default=300)
    ap.add_argument('--no-strict', action='store_true')
    ap.add_argument('--ops-token', default=os.getenv('OPS_TOKEN'))
    ap.add_argument('--load-dotenv', action='store_true')
    ap.add_argument('--preflight-binance', action='store_true', help='Run tools/binance_smoke.py public+private before run')
    args = ap.parse_args()

    if args.load_dotenv:
        load_dotenv(ROOT / '.env')
    # sanitize common problematic vars
    sanitize_env_value('EXCHANGE_ID')
    sanitize_env_value('BINANCE_API_KEY')
    sanitize_env_value('BINANCE_API_SECRET')

    # Optional preflight for binance
    if args.preflight_binance:
        smoke = TOOLS_DIR / 'binance_smoke.py'
        if smoke.exists():
            subprocess.run([sys.executable, str(smoke), '--public-only'], cwd=str(ROOT))
            subprocess.run([sys.executable, str(smoke)], cwd=str(ROOT))

    # Prepare dirs
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    EVENTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    # Clear previous events
    try:
        if EVENTS_PATH.exists():
            EVENTS_PATH.unlink()
    except Exception:
        pass

    base_url = f'http://{args.host}:{args.port}'

    api_proc = None
    runner_proc = None
    exit_code = 1
    try:
        # Start API
        api_proc = start_api(args.host, args.port)
        ok = health_check(base_url, allow_503_shadow=True, timeout_sec=15)
        print(f'[health] ready={ok} url={base_url}')

        # Pre-check risk window and optional cooloff
        h_code = run_canary_harness(base_url, args.ops_token, args.minutes)
        if h_code != 0:
            print('Harness signaled stop (risk breach). Continuing to build summary and run gate for artifacts.')

        if is_live_mode():
            # LIVE
            print(f'[runner] LIVE mode detected for {args.minutes} min')
            runner_proc = start_live_runner(args.runner_config)
            time.sleep(max(0, int(args.minutes * 60)))
        else:
            # Shadow traffic
            print(f'[shadow] Generating traffic for {args.minutes} min @ {args.rps} rps → {base_url}/pretrade/check')
            run_shadow_traffic(base_url, args.minutes, args.rps)

        summary_md = build_summary(args.minutes)
        g_code = run_gate(summary_md, time_window_last=args.time_window_last, strict=not args.no_strict)
        exit_code = g_code
        print_metrics_line()
        if g_code != 0:
            print('--- Tail RISK/HEALTH ---')
            tail_risk_health(10)
    finally:
        stop_proc(runner_proc)
        stop_proc(api_proc)

    sys.exit(exit_code)


if __name__ == '__main__':
    main()
