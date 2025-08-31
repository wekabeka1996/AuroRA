#!/usr/bin/env python
#
# How to run (PowerShell on Windows):
#   python -m venv .venv
#   .\.venv\Scripts\Activate.ps1
#   pip install pandas requests ccxt
#   python .\Dataset.py -h
#   python .\Dataset.py --symbol SOL/USDT --timeframe 1m --hours 24 --out .\data\SOL_USDT_1m.csv
#   # or use days instead of hours:
#   python .\Dataset.py --symbol SOO/USDT --timeframe 1m --days 15
#   # optional: public data works without keys; to set API keys:
#   $env:BINANCE_API_KEY="your_key"; $env:BINANCE_API_SECRET="your_secret"
#
# macOS/Linux equivalents:
#   python3 -m venv .venv
#   source .venv/bin/activate
#   pip install pandas requests ccxt
#   python3 ./Dataset.py -h
#   python3 ./Dataset.py --symbol SOL/USDT --timeframe 1m --hours 24 --out ./data/SOL_USDT_1m.csv
#   export BINANCE_API_KEY=your_key; export BINANCE_API_SECRET=your_secret
"""
Dataset.py — lightweight OHLCV loader for Binance.

- Works with ccxt if available; otherwise falls back to Binance public HTTP API.
- Does NOT require API keys for public OHLCV; keys are optional.
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

import pandas as pd

try:  # optional
    import ccxt  # type: ignore
except Exception:  # pragma: no cover
    ccxt = None  # type: ignore

try:  # fallback HTTP client
    import requests
except Exception:  # pragma: no cover
    requests = None  # type: ignore


HTTP_TIMEOUT_SEC = 10
RETRIES = 5
BACKOFF_BASE = 0.4
MAX_BACKOFF = 6.4


def _get_api_keys() -> tuple[Optional[str], Optional[str]]:
    return os.getenv("BINANCE_API_KEY"), os.getenv("BINANCE_API_SECRET")


def create_binance_client(api_key: Optional[str] = None,
                          api_secret: Optional[str] = None) -> Optional[Any]:
    if ccxt is None:
        return None
    if api_key is None or api_secret is None:
        api_key, api_secret = _get_api_keys()
    # Keys are optional for public data
    cfg: dict[str, Any] = {
        'enableRateLimit': True,
        'timeout': int(HTTP_TIMEOUT_SEC * 1000),
        'options': {'adjustForTimeDifference': True},
    }
    if api_key and api_secret:
        cfg['apiKey'] = api_key
        cfg['secret'] = api_secret
    return ccxt.binance(cfg)  # type: ignore[attr-defined]


def _interval_ms(timeframe: str) -> int:
    mapping = {
        '1m': 60_000, '3m': 180_000, '5m': 300_000, '15m': 900_000, '30m': 1_800_000,
        '1h': 3_600_000, '2h': 7_200_000, '4h': 14_400_000, '6h': 21_600_000, '8h': 28_800_000, '12h': 43_200_000,
        '1d': 86_400_000, '3d': 259_200_000, '1w': 604_800_000, '1M': 2_592_000_000,
    }
    if timeframe not in mapping:
        raise ValueError(f"Unsupported timeframe '{timeframe}'")
    return mapping[timeframe]


def _http_fetch_klines(symbol: str, timeframe: str, start_ms: int, end_ms: int) -> list[list[Any]]:
    if requests is None:
        raise RuntimeError("requests not available and ccxt unavailable; cannot fetch data")
    base = 'https://api.binance.com'
    path = '/api/v3/klines'
    rows: list[list[Any]] = []
    cursor = int(start_ms)
    step = _interval_ms(timeframe)
    end_ms = int(end_ms)
    while cursor < end_ms:
        # request up to 1000 candles but do not cross end_ms
        remaining_candles = max(1, int((end_ms - cursor) // step))
        batch = min(1000, remaining_candles)
        params = {
            'symbol': symbol.replace('/', '').upper(),
            'interval': timeframe,
            'startTime': cursor,
            'limit': batch,
        }
        resp = requests.get(base + path, params=params, timeout=HTTP_TIMEOUT_SEC)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            break
        rows.extend(data)
        last_open = int(data[-1][0])
        cursor = last_open + step
        # small pause to be polite
        time.sleep(0.05)
        if len(data) < batch:
            break
    # Normalize to [ts, open, high, low, close, volume]
    out: list[list[Any]] = []
    for r in rows:
        out.append([r[0], float(r[1]), float(r[2]), float(r[3]), float(r[4]), float(r[5])])
    return out


def fetch_ohlcv_df(symbol: str = 'SUI/USDT',
                   timeframe: str = '1m',
                   hours: int = 24,
                   exchange: Optional[Any] = None) -> pd.DataFrame:
    """Fetch OHLCV into a pandas DataFrame using ccxt or HTTP fallback.

    Fetches the FULL window for the specified hours (no 1000-row cap) by
    paginating requests until reaching the current time.
    """
    now_ms = int(datetime.now(timezone.utc).timestamp() * 1000)
    since_ms = int((datetime.now(timezone.utc) - timedelta(hours=hours)).timestamp() * 1000)

    # Try ccxt first if exchange/client available
    last_exc: Optional[Exception] = None
    if exchange is None:
        exchange = create_binance_client()

    if exchange is not None and ccxt is not None:
        for attempt in range(1, RETRIES + 1):
            try:
                # paginate via since + step
                rows: list[list[Any]] = []
                cursor = since_ms
                step = _interval_ms(timeframe)
                while cursor < now_ms:
                    batch = min(1000, max(1, (now_ms - cursor) // step))
                    part = exchange.fetch_ohlcv(symbol, timeframe, cursor, batch)  # type: ignore[attr-defined]
                    if not part:
                        break
                    rows.extend(part)
                    last_open = int(part[-1][0])
                    cursor = last_open + step
                    if len(part) < batch:
                        break
                    time.sleep(0.05)
                if not rows:
                    raise RuntimeError('empty response')
                df = pd.DataFrame(rows, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
                df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
                df.set_index('timestamp', inplace=True)
                return df
            except Exception as e:  # network/backoff, then fallback to HTTP
                last_exc = e
                time.sleep(min(MAX_BACKOFF, BACKOFF_BASE * (2 ** (attempt - 1))))

    # Fallback: HTTP klines (paginate until now_ms)
    ohlcv = _http_fetch_klines(symbol, timeframe, since_ms, now_ms)
    df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    df.set_index('timestamp', inplace=True)
    return df


def _main() -> None:
    ap = argparse.ArgumentParser(description='Fetch Binance OHLCV and save to CSV (no API key required)')
    ap.add_argument('--symbol', default='SUI/USDT')
    ap.add_argument('--timeframe', default='1m')
    ap.add_argument('--hours', type=int, default=24, help='Lookback in hours (ignored if --days provided)')
    ap.add_argument('--days', type=int, default=None, help='Lookback in whole days (overrides --hours)')
    ap.add_argument('--out', default=None, help='CSV path to write (default: print head only)')
    args = ap.parse_args()

    lookback_hours = args.hours if (args.days is None) else max(1, int(args.days) * 24)
    df = fetch_ohlcv_df(symbol=args.symbol, timeframe=args.timeframe, hours=lookback_hours)
    out_path: Optional[Path]
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
    else:
        # Auto-create data/ and save with a sensible filename
        safe_symbol = args.symbol.replace('/', '_').replace('-', '')
        out_dir = Path('data')
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"{safe_symbol}_{args.timeframe}.csv"

    df.to_csv(out_path)
    print(f"Saved {len(df)} rows to {out_path}")


if __name__ == '__main__':
    _main()
