import argparse
import os
from datetime import datetime

import pandas as pd
import sys
from pathlib import Path
# Ensure project root on sys.path when running from scripts/
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.ingester import DataIngester
from data_pipeline.utils import ensure_time_grid


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--timeframe', default='1h')
    parser.add_argument('--start', required=True, help='e.g. 2023-01-01')
    parser.add_argument('--end', required=True, help='e.g. 2024-01-01')
    parser.add_argument('--outdir', default='data/processed')
    parser.add_argument('--source', default='binance', choices=['binance', 'polygon', 'historical'])
    args = parser.parse_args()

    os.makedirs(args.outdir, exist_ok=True)

    di = DataIngester()
    raw = di.fetch_ohlcv(args.source, symbol=args.symbol, timeframe=args.timeframe, start=args.start, end=args.end)
    raw = ensure_time_grid(raw, args.timeframe)
    if raw.empty:
        raise SystemExit('No data fetched, check symbol/timeframe/date range')

    feats = di.calculate_features(raw)
    # simple chronological split 70/15/15
    n = len(feats)
    n_train = int(n * 0.7)
    n_val = int(n * 0.15)
    train = feats.iloc[:n_train]
    val = feats.iloc[n_train:n_train + n_val]
    test = feats.iloc[n_train + n_val:]

    train_path = os.path.join(args.outdir, 'train.parquet')
    val_path = os.path.join(args.outdir, 'val.parquet')
    test_path = os.path.join(args.outdir, 'test.parquet')

    train.to_parquet(train_path)
    val.to_parquet(val_path)
    test.to_parquet(test_path)

    print(f"Saved: {train_path} ({len(train)}), {val_path} ({len(val)}), {test_path} ({len(test)})")


if __name__ == '__main__':
    main()
