#!/usr/bin/env python3
"""Seed deterministic synthetic aurora event flows for canary preflight.

Writes JSONL using AuroraEventLogger.emit through ExecutionService.place() paths.
"""
from __future__ import annotations

import argparse
import json
import random
from decimal import Decimal
from pathlib import Path
from typing import List
import time
import sys
import os

# Ensure repo root is on sys.path so 'core' and other top-level packages can be imported
ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.aurora_event_logger import AuroraEventLogger
from core.execution.execution_service import ExecutionService
from core.execution.router_v2 import OrderIntent, MarketSpec


def _make_market() -> MarketSpec:
    return MarketSpec(
        tick_size=Decimal('0.01'),
        lot_size=Decimal('0.001'),
        min_notional=Decimal('1.0'),
        maker_fee_bps=2,
        taker_fee_bps=5,
        best_bid=Decimal('100.00'),
        best_ask=Decimal('100.05'),
        spread_bps=0.5,
        mid=Decimal('100.025')
    )


def _make_intent(seed: int, scenario: str) -> OrderIntent:
    random.seed(seed)
    intent_id = f"synt-{scenario}-{seed}"
    ts_ms = int(time.time() * 1000)
    side = 'BUY' if random.random() < 0.5 else 'SELL'
    intent = OrderIntent(
        intent_id=intent_id,
        timestamp_ms=ts_ms,
        symbol='SOON',
        side=side,
        dir=(1 if side == 'BUY' else -1),
        strategy_id='synth',
        expected_return_bps=10,
        stop_dist_bps=100,
        tp_targets_bps=[50],
        risk_ctx={'equity_usd': '10000', 'cvar_curr_usd': '0'},
        regime_ctx={'governance': 'shadow'},
        exec_prefs={'post_only': False, 'tif': 'GTC'},
    )
    return intent


def _run_scenario(scenario: str, seed: int, n: int, out: Path, cfg: dict):
    # deterministic time generator for this scenario
    class _TimeGen:
        def __init__(self, base: float):
            self.base = base
            self.i = 0
        def __call__(self) -> float:
            self.i += 1
            return float(self.base) + float(self.i) * 0.001

    tg = _TimeGen(base=1600000000 + seed)
    orig_time = time.time
    time.time = tg
    logger = AuroraEventLogger(path=out)
    # override run id to deterministic value
    logger._run_id = f"synt-{seed}"
    svc = ExecutionService(config=cfg, event_logger=logger)
    market = _make_market()
    for i in range(n):
        sseed = seed + i
        intent = _make_intent(sseed, scenario)
        # tailor per scenario
        if scenario == 'maker':
            intent.exec_prefs['post_only'] = True
            intent.expected_return_bps = 20
        elif scenario == 'taker':
            intent.exec_prefs['post_only'] = False
            intent.expected_return_bps = 5
        elif scenario == 'low_pfill':
            intent.exec_prefs['post_only'] = True
            intent.expected_return_bps = 1
        elif scenario == 'size_zero':
            # force sizing to yield zero by setting equity to 0
            intent.risk_ctx['equity_usd'] = '0'
        elif scenario == 'sla_deny':
            # force high measured latency
            pass

        # measured_latency_ms param: simulate SLA violation for sla_deny
        measured_latency_ms = 240.0 if scenario == 'sla_deny' else 20.0

        # If sla_deny: emit intent, SLA.CHECK (predict) and SLA.DENY (actual) directly to avoid intent-only traces
        if scenario == 'sla_deny':
            try:
                logger.emit('ORDER.INTENT.RECEIVED', { 'intent_id': intent.intent_id, 'symbol': intent.symbol, 'side': intent.side, 'expected_return_bps': intent.expected_return_bps })
                # Predict phase (using same measured as proxy for determinism)
                logger.emit('SLA.CHECK', { 'phase': 'predict', 'latency_ms': measured_latency_ms, 'edge_after_bps': float(intent.expected_return_bps) - 0.01 * measured_latency_ms, 'intent_id': intent.intent_id })
                # Actual deny
                logger.emit('SLA.DENY', { 'phase': 'actual', 'latency_ms': measured_latency_ms, 'edge_after_bps': float(intent.expected_return_bps) - 0.01 * measured_latency_ms, 'intent_id': intent.intent_id })
            except Exception:
                logger.emit('HEALTH.ERROR', {'msg': 'seed sla_deny emit error', 'scenario': scenario})
            continue

        # call place() — it will emit events via the logger
        try:
            svc.place(intent, market, features={'pred_latency_ms': measured_latency_ms}, measured_latency_ms=measured_latency_ms)
        except Exception:
            # ensure any errors still produce a record
            logger.emit('HEALTH.ERROR', {'msg': 'seed scenario error', 'scenario': scenario})
    # restore time
    time.time = orig_time


def _parse_args():
    p = argparse.ArgumentParser()
    p.add_argument('--out', required=True)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--scenarios', type=str, default='maker,taker,low_pfill,size_zero,sla_deny')
    p.add_argument('--n', type=int, default=1)
    p.add_argument('--truncate', action='store_true', help='Remove output file if it exists before seeding')
    return p.parse_args()


def main():
    args = _parse_args()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.truncate and out.exists():
        try:
            out.unlink()
        except Exception:
            pass
    cfg = {}
    scenarios = [s.strip() for s in args.scenarios.split(',') if s.strip()]
    for s in scenarios:
        _run_scenario(s, args.seed, args.n, out, cfg)


if __name__ == '__main__':
    main()
