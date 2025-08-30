#!/usr/bin/env python3
from __future__ import annotations
import argparse
import os
import re
import sys
import pathlib
import subprocess

ROOT = pathlib.Path(__file__).resolve().parent.parent
TOOLS = ROOT / 'tools'
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

def load_dotenv_if_missing(env_path: pathlib.Path) -> None:
    if not env_path.exists():
        return
    for line in env_path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^\s*([^#=]+)\s*=\s*(.*)\s*$', line)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip().strip('"').strip("'")
        # strip inline comments
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        if k and (k not in os.environ or not os.environ.get(k)):
            os.environ[k] = v


def print_masked_keys() -> None:
    ak = os.getenv('BINANCE_API_KEY')
    sk = os.getenv('BINANCE_API_SECRET')
    if ak and sk:
        print('✅ Keys present (masked):')
        print('BINANCE_API_KEY=****' + ak[-4:])
        print('BINANCE_API_SECRET=****' + sk[-4:])
    else:
        print('❌ BINANCE_API_KEY / BINANCE_API_SECRET missing — add to .env or environment and retry.')
        sys.exit(2)


def set_live_env_defaults() -> None:
    # Testnet runner should operate in shadow mode by default (no hard dependency on loaded models)
    # Allow override via existing env if user explicitly wants prod.
    os.environ['AURORA_MODE'] = os.environ.get('AURORA_MODE', 'shadow')
    os.environ['DRY_RUN'] = 'false'
    os.environ.setdefault('EXCHANGE_ID', 'binanceusdm')
    os.environ.setdefault('EXCHANGE_TESTNET', 'true')
    os.environ.setdefault('EXCHANGE_USE_FUTURES', 'true')
    os.environ.setdefault('BINANCE_RECV_WINDOW', '20000')
    # cautious risk profile
    os.environ.setdefault('AURORA_SIZE_SCALE', '0.05')
    os.environ.setdefault('AURORA_MAX_CONCURRENT', '1')
    os.environ.setdefault('AURORA_DD_DAY_PCT', '1.0')
    # signals/gates
    os.environ.setdefault('PRETRADE_ORDER_PROFILE', 'er_before_slip')
    # Match API expectation: AURORA_PI_MIN_BPS (slightly lower by default on testnet to register at least one accept)
    os.environ.setdefault('AURORA_PI_MIN_BPS', '1.0')
    # Tune slip estimation fraction for ER calc on testnet
    os.environ.setdefault('AURORA_SLIP_FRACTION', '0.25')
    os.environ.setdefault('AURORA_LATENCY_GUARD_MS', '55')
    os.environ.setdefault('AURORA_LATENCY_HARD_HALT_MS', '70')
    os.environ.setdefault('TRAP_GUARD', 'on')
    # In LIVE (DRY_RUN=false) ensure keys are present early
    if os.environ.get('DRY_RUN', '').lower() in {'false','0','no'}:
        if not os.getenv('BINANCE_API_KEY') or not os.getenv('BINANCE_API_SECRET'):
            print('❌ LIVE run requires BINANCE_API_KEY/SECRET — set them in .env or environment.')
            sys.exit(2)


def run_smoke(private: bool = True) -> int:
    smoke = TOOLS / 'binance_smoke.py'
    if not smoke.exists():
        return 0
    args = [sys.executable, str(smoke)]
    if not private:
        args.append('--public-only')
    return subprocess.run(args, cwd=str(ROOT)).returncode


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--minutes', type=int, default=5)
    ap.add_argument('--load-dotenv', action='store_true')
    ap.add_argument('--preflight', action='store_true')
    ap.add_argument('--runner-config', type=str, default=None, help='Path or name of runner YAML to pass to canary/runner')
    args = ap.parse_args()

    if args.load_dotenv:
        load_dotenv_if_missing(ROOT / '.env')
        # sanitize EXCHANGE_ID if it contains inline comments or trailing spaces
        ex = os.getenv('EXCHANGE_ID')
        if ex is not None:
            ex = re.split(r"\s+#", ex.strip().strip('"').strip("'"), maxsplit=1)[0].strip()
            os.environ['EXCHANGE_ID'] = ex

    print_masked_keys()

    set_live_env_defaults()

    if args.preflight:
        # public then private
        rc1 = run_smoke(private=False)
        rc2 = run_smoke(private=True)
        if rc1 != 0 or rc2 != 0:
            print('❌ binance_smoke failed — check keys or network')
            sys.exit(1)
        print('✅ binance_smoke OK (public + private)')

    # hand over to run_canary with minimal args (+ optional runner-config)
    sys.argv = ['run_canary.py', '--minutes', str(args.minutes)]
    if args.runner_config:
        sys.argv += ['--runner-config', args.runner_config]
    from tools.run_canary import main as canary_main
    canary_main()


if __name__ == '__main__':
    main()
