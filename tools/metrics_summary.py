"""
Metrics summary tool for analyzing trading session metrics.
"""
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Dict, Any, List
import time

# Global variable for root directory (can be monkeypatched in tests)
ROOT = Path(__file__).parent.parent


def main(window_sec: int = 3600, out_path: str = None) -> Dict[str, Any]:
    """Main metrics summary function."""
    if out_path is None:
        out_path = str(ROOT / 'reports' / 'summary_gate_status.json')

    # Ensure output directory exists
    out_path_obj = Path(out_path)
    out_path_obj.parent.mkdir(parents=True, exist_ok=True)

    # Process logs
    logs_dir = ROOT / 'logs'
    data = process_logs(logs_dir, window_sec)

    # Write to file
    with open(out_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, default=str)

    return data


def process_logs(logs_dir: Path, window_sec: int) -> Dict[str, Any]:
    """Process all log files and generate metrics summary."""
    # Initialize data structures
    orders_success = []
    orders_failed = []
    orders_denied = []
    aurora_events = []

    # Read log files if they exist
    for log_file in ['orders_success.jsonl', 'orders_failed.jsonl', 'orders_denied.jsonl', 'aurora_events.jsonl']:
        log_path = logs_dir / log_file
        if log_path.exists():
            with open(log_path, 'r', encoding='utf-8') as f:
                for line in f:
                    if line.strip():
                        try:
                            record = json.loads(line.strip())
                            if 'orders_success' in log_file:
                                orders_success.append(record)
                            elif 'orders_failed' in log_file:
                                orders_failed.append(record)
                            elif 'orders_denied' in log_file:
                                orders_denied.append(record)
                            elif 'aurora_events' in log_file:
                                aurora_events.append(record)
                        except json.JSONDecodeError:
                            continue

    # Calculate metrics
    total_orders = len(orders_success) + len(orders_failed) + len(orders_denied)
    success_count = len(orders_success)
    failed_count = len(orders_failed)
    denied_count = len(orders_denied)

    # Orders statistics
    orders_stats = {
        'total': total_orders,
        'success_pct': (success_count / total_orders) if total_orders > 0 else 0.0,
        'rejected_pct': (failed_count / total_orders) if total_orders > 0 else 0.0,
        'denied_pct': (denied_count / total_orders) if total_orders > 0 else 0.0
    }

    # Reasons statistics
    reasons_counter = Counter()
    for order in orders_failed + orders_denied:
        if 'reason_code' in order:
            reasons_counter[order['reason_code']] += 1

    reasons_top5 = dict(reasons_counter.most_common(5))

    # Latency statistics
    latency_stats = calculate_latency_stats(aurora_events)

    # Market snapshot
    market_stats = calculate_market_stats(orders_success)

    # Gates statistics
    gates_stats = Counter()
    for order in orders_denied:
        if 'reason_code' in order:
            gates_stats[order['reason_code']] += 1

    # Rewards statistics
    rewards_stats = Counter()
    for event in aurora_events:
        if event.get('event_code') == 'REWARD.TP':
            rewards_stats['TP'] += 1
        elif event.get('event_code') == 'REWARD.TRAIL':
            rewards_stats['TRAIL'] += 1

    # Sanity check
    total_records = len(orders_success) + len(orders_failed) + len(orders_denied) + len(aurora_events)
    sanity = {
        'records': total_records,
        'note': 'insufficient_data' if total_records == 0 else None
    }

    return {
        'orders': orders_stats,
        'reasons_top5': reasons_top5,
        'latency_ms': latency_stats,
        'market_snapshot': market_stats,
        'gates': dict(gates_stats),
        'rewards': dict(rewards_stats),
        'sanity': sanity
    }


def calculate_latency_stats(events: List[Dict]) -> Dict[str, Any]:
    """Calculate latency percentiles from aurora events."""
    # Group events by correlation ID
    event_chains = defaultdict(list)
    for event in events:
        cid = event.get('cid')
        if cid:
            event_chains[cid].append(event)

    submit_ack_latencies = []
    ack_fill_latencies = []

    for chain in event_chains.values():
        # Sort by timestamp
        chain.sort(key=lambda x: x.get('ts_ns', 0))

        submit_ts = None
        ack_ts = None
        fill_ts = None

        for event in chain:
            event_code = event.get('event_code')
            ts_ns = event.get('ts_ns', 0)

            if event_code == 'ORDER.SUBMIT':
                submit_ts = ts_ns
            elif event_code == 'ORDER.ACK':
                ack_ts = ts_ns
            elif event_code == 'ORDER.FILL':
                fill_ts = ts_ns

        # Calculate latencies in milliseconds
        if submit_ts and ack_ts:
            latency_ms = (ack_ts - submit_ts) / 1_000_000
            submit_ack_latencies.append(latency_ms)

        if ack_ts and fill_ts:
            latency_ms = (fill_ts - ack_ts) / 1_000_000
            ack_fill_latencies.append(latency_ms)

    def safe_percentiles(data, p):
        if not data:
            return 0.0
        return statistics.quantiles(data, n=100)[p-1] if len(data) >= 100 else statistics.mean(data)

    return {
        'submit_ack': {
            'p50': safe_percentiles(submit_ack_latencies, 50),
            'p90': safe_percentiles(submit_ack_latencies, 90),
            'p99': safe_percentiles(submit_ack_latencies, 99)
        },
        'ack_done': {
            'p50': safe_percentiles(ack_fill_latencies, 50),
            'p90': safe_percentiles(ack_fill_latencies, 90),
            'p99': safe_percentiles(ack_fill_latencies, 99)
        }
    }


def calculate_market_stats(orders_success: List[Dict]) -> Dict[str, float]:
    """Calculate market statistics from successful orders."""
    spread_values = []
    vol_std_values = []

    for order in orders_success:
        context = order.get('context', {})
        if 'spread_bps' in order:
            spread_values.append(order['spread_bps'])
        if 'vol_std_bps' in order:
            vol_std_values.append(order['vol_std_bps'])

    return {
        'spread_bps_avg': statistics.mean(spread_values) if spread_values else 0.0,
        'vol_std_bps_avg': statistics.mean(vol_std_values) if vol_std_values else 0.0
    }


def process_events(events_file: str) -> Dict[str, Any]:
    """Process events file and return metrics."""
    return main()


if __name__ == "__main__":
    main()