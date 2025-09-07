#!/usr/bin/env python3
"""Simple Binance REST + WS smoke for symbols.

Writes JSONL with entries per received tick. Supports:
- WebSocket miniTicker (python-binance) with optional --ws-only
- REST polling fallback (no extra deps) with --rest-only
- Testnet via --testnet (REST uses https://testnet.binance.vision)

Record format per line:
{"ts": 1690000000000, "symbol": "BTCUSDT", "bid": 68000.1, "ask": 68000.3, "spread_bps": 0.29, "ok": true}
"""

import argparse
import asyncio
import json
import time
import os
import random
from typing import Dict, List
from pathlib import Path

import requests

try:
    from binance import AsyncClient, BinanceSocketManager
except Exception:
    # Provide a helpful error when package missing
    AsyncClient = None
    BinanceSocketManager = None


async def ws_listener(symbols: List[str], timeout: int, out_path: Path, testnet: bool = False) -> Dict[str, int]:
    """Listen to miniTicker WS and write ticks.

    Requires python-binance installed. Respects --testnet.
    """
    if AsyncClient is None or BinanceSocketManager is None:
        raise RuntimeError("python-binance not installed. Use --rest-only or pip install python-binance")

    client = await AsyncClient.create(testnet=testnet)
    bsm = BinanceSocketManager(client)

    sockets = []
    for s in symbols:
        # use miniTicker socket for basic best bid/ask info
        sockets.append(bsm.mini_ticker_socket(symbol=s.lower()))

    # Open sockets
    tasks = [asyncio.create_task(sock.__aenter__()) for sock in sockets]
    conns = await asyncio.gather(*tasks)

    start = time.time()
    counts: Dict[str, int] = {s: 0 for s in symbols}

    with out_path.open('a', encoding='utf-8') as f:
        while time.time() - start < timeout:
            for symbol, conn in zip(symbols, conns):
                try:
                    msg = await conn.recv()
                except Exception:
                    continue
                # miniTicker payload example contains 'b' and 'a'
                bid = float(msg.get('b', 0)) if msg.get('b') else None
                ask = float(msg.get('a', 0)) if msg.get('a') else None
                spread_bps = None
                if bid and ask and bid > 0:
                    spread_bps = (ask - bid) / bid * 10000.0

                rec = {
                    'ts': int(time.time() * 1e3),
                    'symbol': symbol,
                    'bid': bid,
                    'ask': ask,
                    'spread_bps': spread_bps,
                    'ok': True
                }
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                counts[symbol] += 1
            # small sleep to avoid tight loop
            await asyncio.sleep(0.01)

    # close
    for conn in conns:
        try:
            await conn.__aexit__(None, None, None)
        except Exception:
            pass
    await client.close_connection()

    return counts


def _rest_base_url(testnet: bool) -> str:
    return "https://testnet.binance.vision" if testnet else "https://api.binance.com"


def _rest_book_ticker(symbol: str, testnet: bool) -> Dict[str, float | None]:
    """Fetch best bid/ask via REST public API.

    Uses /api/v3/ticker/bookTicker which is public and does not require auth.
    """
    base = _rest_base_url(testnet)
    url = f"{base}/api/v3/ticker/bookTicker"
    # Exponential backoff with jitter on 429/418
    backoff_s = 0.5
    for attempt in range(5):
        try:
            resp = requests.get(url, params={"symbol": symbol.upper()}, timeout=3)
            if resp.status_code in (429, 418):
                # rate limited
                jitter = backoff_s * (0.9 + 0.2 * random.random())
                time.sleep(min(8.0, jitter))
                backoff_s = min(8.0, backoff_s * 2)
                continue
            resp.raise_for_status()
            data = resp.json()
            bid = float(data["bidPrice"]) if data.get("bidPrice") else None
            ask = float(data["askPrice"]) if data.get("askPrice") else None
            return {"bid": bid, "ask": ask, "rate_limit_hit": False}
        except requests.HTTPError as he:  # noqa: F841
            # Non-2xx other than 429/418
            break
        except Exception:
            # Network error; short sleep and retry
            jitter = backoff_s * (0.9 + 0.2 * random.random())
            time.sleep(min(4.0, jitter))
            backoff_s = min(4.0, backoff_s * 2)
            continue
    # Failed or exhausted
    return {"bid": None, "ask": None, "rate_limit_hit": True}


async def rest_poller(symbols: List[str], timeout: int, interval_ms: int, out_path: Path, testnet: bool) -> Dict[str, int]:
    """Poll REST bookTicker at a fixed interval and write ticks."""
    start = time.time()
    counts: Dict[str, int] = {s: 0 for s in symbols}
    rate_limit_hits = 0

    with out_path.open('a', encoding='utf-8') as f:
        while time.time() - start < timeout:
            for symbol in symbols:
                # Run sync HTTP in a thread to avoid blocking event loop
                res = await asyncio.to_thread(_rest_book_ticker, symbol, testnet)
                bid = res.get('bid')
                ask = res.get('ask')
                rate_limit_hit = bool(res.get('rate_limit_hit', False))
                if rate_limit_hit:
                    rate_limit_hits += 1
                spread_bps = None
                try:
                    if bid is not None and ask is not None and bid > 0 and ask > 0:
                        spread_bps = (ask - bid) / bid * 10000.0
                except Exception:
                    spread_bps = None
                # Validation
                ok = False
                try:
                    ok = (
                        bid is not None and ask is not None and bid > 0 and ask > 0 and
                        (spread_bps is not None) and spread_bps >= 0 and ask >= bid
                    )
                except Exception:
                    ok = False
                rec = {
                    'ts': int(time.time() * 1e3),
                    'symbol': symbol,
                    'bid': bid,
                    'ask': ask,
                    'spread_bps': spread_bps,
                    'ok': ok,
                    'rate_limit_hit': rate_limit_hit,
                }
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                if ok:
                    counts[symbol] += 1
            # Anti-hot polling: min 50-100ms with ±10% jitter
            base_sleep = max(0.05, interval_ms / 1000.0)
            jitter_factor = 0.9 + 0.2 * random.random()
            await asyncio.sleep(max(0.05, base_sleep * jitter_factor))
    return counts


async def run_async(args) -> int:
    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    symbols = [s.strip().upper() for s in args.symbols.split(',') if s.strip()]
    if not symbols:
        print('No symbols provided. Use --symbols BTCUSDT,ETHUSDT')
        return 2

    # LIVE-first guard: no testnet if BINANCE_ENV=live
    if os.getenv('BINANCE_ENV', '').lower() == 'live' and args.testnet:
        print('Abort: --testnet is not allowed when BINANCE_ENV=live (production policy).')
        return 2

    # Decide modes
    ws_enabled = args.ws_only or (not args.rest_only)
    rest_enabled = args.rest_only or (not args.ws_only)

    # Validate availability
    if ws_enabled and (AsyncClient is None or BinanceSocketManager is None):
        if args.ws_only:
            print('python-binance not installed; install python-binance or use --rest-only')
            return 2
        else:
            print('python-binance not installed; falling back to REST polling')
            ws_enabled = False
            rest_enabled = True

    # Run selected modes concurrently if both enabled
    tasks = []
    if ws_enabled:
        tasks.append(ws_listener(symbols, args.timeout, out_path, args.testnet))
    if rest_enabled:
        tasks.append(rest_poller(symbols, args.timeout, args.interval_ms, out_path, args.testnet))

    if not tasks:
        print('Nothing to run (check flags --ws-only/--rest-only)')
        return 2

    # Remember run window for summary
    start_ts = int(time.time() * 1000)
    results = await asyncio.gather(*tasks, return_exceptions=True)
    end_ts = int(time.time() * 1000)
    merged: Dict[str, int] = {s: 0 for s in symbols}
    for res in results:
        if isinstance(res, dict):
            for k, v in res.items():
                merged[k] = merged.get(k, 0) + int(v)
        else:
            print(f"Warning: task error: {res}")

    print('Counts:', merged)
    # Auto-summary report
    try:
        spreads: List[float] = []
        total = 0
        ok_total = 0
        by_symbol: Dict[str, Dict[str, int]] = {s: {"ok": 0, "total": 0} for s in symbols}
        with out_path.open('r', encoding='utf-8') as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except Exception:
                    continue
                ts = rec.get('ts')
                sym = str(rec.get('symbol', '')).upper()
                if ts is None or sym not in by_symbol:
                    continue
                if not (start_ts <= int(ts) <= end_ts):
                    continue
                total += 1
                by_symbol[sym]['total'] += 1
                if rec.get('ok'):
                    ok_total += 1
                    by_symbol[sym]['ok'] += 1
                    sb = rec.get('spread_bps')
                    try:
                        if sb is not None:
                            spreads.append(float(sb))
                    except Exception:
                        pass
        spreads.sort()
        def _pct(vals: List[float], p: float) -> float | None:
            if not vals:
                return None
            k = max(0, min(len(vals) - 1, int(round((p / 100.0) * (len(vals) - 1)))))
            return vals[k]
        p50 = _pct(spreads, 50.0)
        p95 = _pct(spreads, 95.0)
        ok_pct = (ok_total / total * 100.0) if total > 0 else 0.0
        # Write markdown report
        reports_dir = Path('reports')
        reports_dir.mkdir(parents=True, exist_ok=True)
        rpt = reports_dir / 'binance_smoke.md'
        with rpt.open('w', encoding='utf-8') as rf:
            rf.write('# Binance smoke report\n\n')
            rf.write(f'- Window: {start_ts} .. {end_ts} (ms)\n')
            rf.write(f'- Symbols: {", ".join(symbols)}\n')
            rf.write(f'- Samples (all): {total}, OK: {ok_total} ({ok_pct:.1f}%)\n')
            for s in symbols:
                ok_s = by_symbol[s]['ok']
                tot_s = by_symbol[s]['total']
                pct_s = (ok_s / tot_s * 100.0) if tot_s > 0 else 0.0
                rf.write(f'  - {s}: {ok_s}/{tot_s} ({pct_s:.1f}%)\n')
            rf.write(f'- spread_bps p50: {p50 if p50 is not None else "n/a"}\n')
            rf.write(f'- spread_bps p95: {p95 if p95 is not None else "n/a"}\n')
        print(f'Report written: {rpt}')
    except Exception as e:
        print(f'Note: failed to write summary report: {e}')
    return 0


def main():
    p = argparse.ArgumentParser(description='Binance mini smoke (WS and/or REST)')
    p.add_argument('--symbols', default='SOLUSDT', help='Comma-separated symbols, e.g. BTCUSDT,ETHUSDT')
    p.add_argument('--timeout', type=int, default=60, help='Total run time in seconds')
    p.add_argument('--interval-ms', type=int, default=1000, help='REST polling interval in ms')
    p.add_argument('--out', default=str(Path('logs') / 'binance_smoke.jsonl'), help='Output JSONL path')
    p.add_argument('--ws-only', action='store_true', help='Run only WebSocket miniTicker (requires python-binance)')
    p.add_argument('--rest-only', action='store_true', help='Run only REST polling (no extra deps)')
    p.add_argument('--testnet', action='store_true', help='Use Binance testnet endpoints')
    args = p.parse_args()

    # Allow env overrides for convenience
    if os.getenv('BINANCE_TESTNET') == '1':
        args.testnet = True
    if os.getenv('BINANCE_WS_ONLY') == '1':
        args.ws_only = True
    if os.getenv('BINANCE_REST_ONLY') == '1':
        args.rest_only = True

    exit_code = asyncio.run(run_async(args))
    raise SystemExit(exit_code)


if __name__ == '__main__':
    main()
