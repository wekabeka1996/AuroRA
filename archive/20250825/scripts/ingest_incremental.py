import argparse
import os
from datetime import datetime, timezone

import pandas as pd

import sys
from pathlib import Path
# Ensure project root is on sys.path when running from scripts/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.ingester import DataIngester
from data_pipeline.utils import ensure_time_grid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--timeframe', default='1h')
    parser.add_argument('--start', required=True, help='ISO8601 (UTC), e.g. 2023-01-01')
    parser.add_argument('--end', default=None, help='ISO8601 (UTC), default now')
    parser.add_argument('--outdir', default='data/raw')
    parser.add_argument('--source', default='binance', choices=['binance'])
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)
    safe_symbol = args.symbol.replace('/', '')
    out_path = os.path.join(args.outdir, f"binance_{safe_symbol}_{args.timeframe}.parquet")

    di = DataIngester()

    # Determine start time: resume from last record if file exists
    start = args.start
    if os.path.exists(out_path):
        try:
            existing = pd.read_parquet(out_path)
            if not existing.empty:
                last_ts = existing.index.max()
                # advance one step
                inc = pd.Timedelta(minutes=60) if args.timeframe.endswith('h') else pd.Timedelta(days=1)
                start = (last_ts + inc).strftime('%Y-%m-%dT%H:%M:%SZ')
        except Exception:
            pass

    df = di.fetch_ohlcv(args.source, symbol=args.symbol, timeframe=args.timeframe, start=start, end=args.end)
    df = ensure_time_grid(df, args.timeframe)

    if os.path.exists(out_path):
        try:
            existing = pd.read_parquet(out_path)
            combined = pd.concat([existing, df])
            combined = combined[~combined.index.duplicated(keep='last')]
            combined = combined.sort_index()
            combined.to_parquet(out_path)
            print(f"Appended and saved: {out_path} ({len(combined)} rows)")
            return
        except Exception:
            pass

    df.to_parquet(out_path)
    print(f"Saved new file: {out_path} ({len(df)} rows)")


if __name__ == '__main__':
    main()
