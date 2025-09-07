#!/usr/bin/env python3
"""
Generate sample replay data from CSV files for testing Aurora replay tool.
"""

import json
import os
import pandas as pd
from datetime import datetime
import random

def convert_csv_to_jsonl(csv_path: str, jsonl_path: str, symbol: str, max_rows: int = 1000):
    """Convert CSV OHLCV data to JSONL format for replay."""

    df = pd.read_csv(csv_path, nrows=max_rows)

    events = []
    for idx, row in df.iterrows():
        # Convert timestamp to nanoseconds
        ts = pd.to_datetime(row['timestamp']).timestamp() * 1_000_000_000

        # Create trade event
        event = {
            "timestamp_ns": int(ts),
            "symbol": symbol,
            "type": "trade",
            "price": float(row['close']),
            "volume": float(row['volume']),
            "side": random.choice(["buy", "sell"]),
            "seq": idx
        }
        events.append(event)

        # Add some orderbook events
        if idx % 10 == 0:  # Every 10th event
            ob_event = {
                "timestamp_ns": int(ts + 1000000),  # 1ms later
                "symbol": symbol,
                "type": "orderbook",
                "bids": [
                    [float(row['close']) - 0.0001, 100.0],
                    [float(row['close']) - 0.0002, 200.0]
                ],
                "asks": [
                    [float(row['close']) + 0.0001, 100.0],
                    [float(row['close']) + 0.0002, 200.0]
                ],
                "seq": idx + 1000000
            }
            events.append(ob_event)

    # Sort by timestamp
    events.sort(key=lambda x: x['timestamp_ns'])

    # Write to JSONL
    with open(jsonl_path, 'w', encoding='utf-8') as f:
        for event in events:
            f.write(json.dumps(event, ensure_ascii=False) + '\n')

    print(f"Generated {len(events)} events for {symbol}")

def main():
    """Generate sample replay data."""

    replay_dir = "data/replay_30d"
    os.makedirs(replay_dir, exist_ok=True)

    # Convert available CSV files
    csv_files = [
        ("data/BIO_USDT_1m.csv", "BIOUSDT"),
        ("data/DOGE_USDT_1m.csv", "DOGEUSDT"),
        ("data/SOL_USDT_1m.csv", "SOLUSDT"),
    ]

    for csv_path, symbol in csv_files:
        if os.path.exists(csv_path):
            jsonl_path = os.path.join(replay_dir, f"{symbol.lower()}_trades.jsonl")
            convert_csv_to_jsonl(csv_path, jsonl_path, symbol, max_rows=500)

    print("Sample replay data generation completed!")

if __name__ == "__main__":
    main()