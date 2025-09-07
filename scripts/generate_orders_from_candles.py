"""
Simple generator: convert 1m candle CSV into JSONL.gz of order lifecycle events
Fields included to satisfy notebook's compute_metrics:
- oid (order id), ts_ms, event_code ('ORDER_SUBMIT','ORDER_ACK','ORDER_FILL','ORDER_CANCEL')
- order_qty / qty, filled_qty / fill_qty
- liquidity / taker_maker
- slippage_bps, is_bps, spread_bps, impact_bps, fees_bps

This is a heuristic simulator for demo/testing only.
"""
import gzip
import json
import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime, timedelta

SRC = Path('data/SOL_USDT_1m.csv')
OUT = Path('datasets/real_SOL_orders.jsonl.gz')
np.random.seed(42)

df = pd.read_csv(SRC, parse_dates=['timestamp'])

records = 0
with gzip.open(OUT, 'wt', encoding='utf-8') as f:
    oid_seq = 0
    for _, row in df.iterrows():
        ts_base = row['timestamp']
        vol = max(1.0, float(row.get('volume', 0.0)))
        # number of orders proportional to log(volume)
        n_orders = int(min(10, max(1, int(np.log1p(vol) * 1.5))))
        for i in range(n_orders):
            oid_seq += 1
            oid = f"S-{oid_seq}"
            # order size proportional to minute volume
            qty = max(1, int(max(1, vol/n_orders) * np.random.uniform(0.01, 0.2)))
            submit_offset_ms = int(np.random.uniform(0, 40000))  # within the minute
            ack_delay_ms = int(abs(np.random.normal(5, 10)))
            fill_delay_ms = int(abs(np.random.exponential(50)))
            submit_ts = int(ts_base.timestamp() * 1000) + submit_offset_ms
            ack_ts = submit_ts + ack_delay_ms
            # decide if filled or cancelled partly
            fill_prob = min(0.95, 0.4 + 0.6 * np.random.rand())
            if np.random.rand() < 0.9:
                # ack occurs
                # submit
                rec = {
                    'oid': oid,
                    'ts_ms': submit_ts,
                    'event_code': 'ORDER_SUBMIT',
                    'qty': qty,
                    'liquidity': 'maker' if np.random.rand() < 0.5 else 'taker'
                }
                f.write(json.dumps(rec) + '\n')
                records += 1
                # ack
                rec = {
                    'oid': oid,
                    'ts_ms': ack_ts,
                    'event_code': 'ORDER_ACK',
                    'qty': qty,
                }
                f.write(json.dumps(rec) + '\n')
                records += 1
            else:
                # lost ack, treat submit only
                rec = {
                    'oid': oid,
                    'ts_ms': submit_ts,
                    'event_code': 'ORDER_SUBMIT',
                    'qty': qty,
                    'liquidity': 'maker'
                }
                f.write(json.dumps(rec) + '\n')
                records += 1

            # final: either fill or cancel
            if np.random.rand() < fill_prob:
                filled = int(qty * (0.7 + 0.3 * np.random.rand()))
                fill_ts = ack_ts + fill_delay_ms
                slippage_bps = float(np.random.normal(1.0, 0.5))
                rec = {
                    'oid': oid,
                    'ts_ms': fill_ts,
                    'event_code': 'ORDER_FILL',
                    'qty': qty,
                    'fill_qty': filled,
                    'filled_qty': filled,
                    'slippage_bps': round(slippage_bps,6),
                    'is_bps': round(slippage_bps + np.random.normal(0.1,0.2),6),
                    'spread_bps': round(abs(np.random.normal(20,5)),6),
                    'impact_bps': round(abs(np.random.normal(0.7,0.3)),6),
                    'fees_bps': round(abs(np.random.normal(0.5,0.2)),6),
                }
                f.write(json.dumps(rec) + '\n')
                records += 1
            else:
                cancel_ts = ack_ts + int(np.random.uniform(10, 30000))
                rec = {
                    'oid': oid,
                    'ts_ms': cancel_ts,
                    'event_code': 'ORDER_CANCEL',
                    'qty': qty,
                }
                f.write(json.dumps(rec) + '\n')
                records += 1

print(f'WROTE {OUT} rows=', records)
