import argparse
import yaml
from data_pipeline.ingester import DataIngester


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', default='binance')
    parser.add_argument('--symbol', default='BTC/USDT')
    parser.add_argument('--timeframe', default='1h')
    parser.add_argument('--start', default='2023-01-01')
    parser.add_argument('--end', default='2024-01-01')
    parser.add_argument('--out', default='data/historical.parquet')
    args = parser.parse_args()

    di = DataIngester()
    df = di.fetch_ohlcv(args.source, symbol=args.symbol, timeframe=args.timeframe, start=args.start, end=args.end)
    df.to_parquet(args.out)
    print(f"Saved historical data to {args.out} ({len(df)} rows)")


if __name__ == '__main__':
    main()
