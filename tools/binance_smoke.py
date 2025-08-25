from __future__ import annotations

import argparse
import os
import sys
import time
from typing import Any
from pathlib import Path
import re

try:
    import ccxt  # type: ignore
except Exception as e:  # pragma: no cover
    print(f"BINANCE_SMOKE: FAIL reason=ccxt_import_error err={e}")
    sys.exit(1)


def env_bool(name: str, default: bool) -> bool:
    v = os.getenv(name)
    if v is None:
        return default
    return str(v).lower() in {"1", "true", "yes", "on"}


def load_dotenv(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding='utf-8').splitlines():
        m = re.match(r'^\s*([^#=]+)\s*=\s*(.*)\s*$', raw)
        if not m:
            continue
        k, v = m.group(1).strip(), m.group(2).strip().strip('"').strip("'")
        v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
        if k and (k not in os.environ or not os.environ.get(k)):
            os.environ[k] = v


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbol", default=os.getenv("SYMBOL", "BTC/USDT"))
    ap.add_argument("--public-only", action="store_true")
    args = ap.parse_args()

    # Load .env for convenience (local process only)
    try:
        load_dotenv(Path.cwd() / '.env')
    except Exception:
        pass

    exchange_id = os.getenv("EXCHANGE_ID", "binanceusdm")
    exchange_id = (exchange_id or '').split('#', 1)[0].strip()
    testnet = env_bool("EXCHANGE_TESTNET", True)
    recv_window = int(os.getenv("BINANCE_RECV_WINDOW", "20000"))

    # Build client
    fallback_usdm = False
    try:
        ex_class = getattr(ccxt, exchange_id)
    except AttributeError:
        # Fallback: some ccxt versions don't expose binanceusdm class; use binance with futures defaultType
        if exchange_id == "binanceusdm" and hasattr(ccxt, "binance"):
            ex_class = getattr(ccxt, "binance")
            fallback_usdm = True
        else:
            print(f"BINANCE_SMOKE: FAIL reason=unknown_exchange id={exchange_id}          # ccxt id for USDT-M futures")
            sys.exit(1)

    options = {
        "defaultType": "future" if (exchange_id.endswith("usdm") or fallback_usdm) else "spot",
        "adjustForTimeDifference": True,
        "recvWindow": recv_window,
    }
    client = ex_class({
        "enableRateLimit": True,
        "timeout": 20000,
        "options": options,
    })

    # Sandbox mode
    try:
        if testnet and hasattr(client, "set_sandbox_mode"):
            client.set_sandbox_mode(True)
    except Exception:
        pass

    # Public checks
    try:
        srv_time = None
        if hasattr(client, "fetch_time"):
            srv_time = client.fetch_time()
        markets = client.load_markets()
        ob = client.fetch_order_book(args.symbol, limit=5)
        best_bid = ob.get("bids", [[None]])[0][0]
        best_ask = ob.get("asks", [[None]])[0][0]
        print(f"PUBLIC ok time={srv_time} symbol={args.symbol} bid={best_bid} ask={best_ask}")
    except Exception as e:
        print(f"BINANCE_SMOKE: FAIL reason=public_checks err={e}")
        sys.exit(1)

    if args.public_only:
        print("BINANCE_SMOKE: OK mode=public")
        sys.exit(0)

    # Private checks
    api_key = os.getenv("BINANCE_API_KEY") or os.getenv("API_KEY")
    api_secret = os.getenv("BINANCE_API_SECRET") or os.getenv("API_SECRET")
    if not api_key or not api_secret:
        print("BINANCE_SMOKE: FAIL reason=missing_keys")
        sys.exit(1)

    client.apiKey = api_key
    client.secret = api_secret

    try:
        bal = client.fetch_balance()
        # Positions for futures if supported
        pos_info: Any = None
        if hasattr(client, "fetch_positions"):
            try:
                pos_info = client.fetch_positions()
            except Exception:
                pos_info = None
        spot_usdt = bal.get("USDT", {}).get("free") if isinstance(bal, dict) else None
        npos = len(pos_info) if isinstance(pos_info, list) else 0
        print(f"PRIVATE ok usdt_free={spot_usdt} positions={npos}")
    except Exception as e:
        print(f"BINANCE_SMOKE: FAIL reason=private_checks err={e}")
        sys.exit(1)

    # Do not place orders when DRY_RUN=true; only log an intent
    if env_bool("DRY_RUN", True):
        print("PRIVATE note: DRY_RUN=true — would place reduceOnly test order (skipped)")
        print("BINANCE_SMOKE: OK mode=private_dry_run")
        sys.exit(0)

    # If someone insists on not dry-run, still be cautious: skip sending orders here.
    print("BINANCE_SMOKE: OK mode=private_no_order")
    sys.exit(0)


if __name__ == "__main__":
    main()
