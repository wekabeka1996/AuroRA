#!/usr/bin/env python3
from __future__ import annotations

"""
Aurora — run_live
=================

Minimal live runner that:
  • Loads SSOT-config
  • Fetches top-of-book from the selected exchange (Binance/Gate)
  • Computes a route decision (maker/taker) via `execution/router.Router`
  • Places an order using exchange adapter with idempotent client ID

Design
------
- Pure-stdlib HTTP client (urllib) implements `HttpClient` Protocol
- No external deps; production deployments may replace `StdlibHttpClient`
- Safe defaults: pre-trade edge is user-provided; hazard model is optional

Examples
--------
Binance taker market:
    python -m scripts.run_live \
        --exchange binance --api-key $KEY --api-secret $SEC \
        --symbol BTCUSDT --side buy --type market --quantity 0.001 \
        --edge-bps 5 --latency-ms 10

Maker limit on Gate:
    python -m scripts.run_live \
        --exchange gate --api-key $K --api-secret $S \
        --symbol BTC_USDT --side buy --type limit --quantity 0.001 \
        --edge-bps 3 --latency-ms 15
"""

import argparse
import json
import ssl
import sys
import time
from dataclasses import dataclass
from typing import Any, Mapping, Optional
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from pathlib import Path

from core.config.loader import load_config
from core.execution.exchange.common import HttpClient, OrderRequest, OrderType, Side, TimeInForce
from core.execution.exchange.binance import BinanceExchange
from core.execution.exchange.gate import GateExchange
from core.execution.router import Router, QuoteSnapshot


# --------------------- stdlib HTTP client ---------------------

class StdlibHttpClient(HttpClient):
    def request(
        self,
        method: str,
        url: str,
        *,
        params: Optional[Mapping[str, object]] = None,
        headers: Optional[Mapping[str, str]] = None,
        json: Optional[object] = None,
    ) -> Mapping[str, object]:
        if params:
            qs = urlencode(params, doseq=True)
            sep = '&' if ('?' in url) else '?'
            url = f"{url}{sep}{qs}"
        data = None
        hdrs = dict(headers or {})
        if json is not None:
            body = (json if isinstance(json, str) else __import__('json').dumps(json)).encode('utf-8')
            data = body
            hdrs.setdefault('Content-Type', 'application/json')
        req = Request(url=url, method=method.upper(), headers=hdrs, data=data)
        ctx = ssl.create_default_context()
        with urlopen(req, context=ctx, timeout=10) as resp:
            raw = resp.read().decode('utf-8')
            try:
                return __import__('json').loads(raw)
            except Exception:
                return {"raw": raw, "status": resp.status}


# --------------------- public book snapshots ---------------------

@dataclass
class Book:
    bid: float
    ask: float


def fetch_book(exchange: str, symbol: str, *, futures: bool, http: StdlibHttpClient) -> Book:
    ex = exchange.lower()
    if ex == 'binance':
        base = 'https://fapi.binance.com' if futures else 'https://api.binance.com'
        path = '/fapi/v1/ticker/bookTicker' if futures else '/api/v3/ticker/bookTicker'
        data = http.request('GET', base + path, params={'symbol': symbol.replace('-', '').upper()})
        bid_val = data.get('bidPrice', 0.0)
        ask_val = data.get('askPrice', 0.0)
        try:
            bid = float(str(bid_val)) if bid_val is not None else 0.0
        except (ValueError, TypeError):
            bid = 0.0
        try:
            ask = float(str(ask_val)) if ask_val is not None else 0.0
        except (ValueError, TypeError):
            ask = 0.0
        return Book(bid=bid, ask=ask)
    if ex == 'gate':
        base = 'https://api.gateio.ws/api/v4'
        data = http.request('GET', base + '/spot/tickers', params={'currency_pair': symbol})
        # response is a list of dicts
        row = {}
        if isinstance(data, list) and len(data) > 0:
            first_item = data[0]  # type: ignore
            if isinstance(first_item, dict):
                row = first_item
        elif isinstance(data, dict):
            row = data
        bid_val = row.get('highest_bid', 0.0) if isinstance(row, dict) else 0.0
        ask_val = row.get('lowest_ask', 0.0) if isinstance(row, dict) else 0.0
        try:
            bid = float(str(bid_val)) if bid_val is not None else 0.0
        except (ValueError, TypeError):
            bid = 0.0
        try:
            ask = float(str(ask_val)) if ask_val is not None else 0.0
        except (ValueError, TypeError):
            ask = 0.0
        return Book(bid=bid, ask=ask)
    raise SystemExit(f"unknown exchange '{exchange}'")


# --------------------- main ---------------------

def main() -> None:
    ap = argparse.ArgumentParser(description='Aurora live runner')
    ap.add_argument('--exchange', required=True, choices=['binance', 'gate'])
    ap.add_argument('--futures', action='store_true', help='Binance futures endpoints')
    ap.add_argument('--api-key', required=True)
    ap.add_argument('--api-secret', required=True)
    ap.add_argument('--symbol', required=True, help='e.g., BTCUSDT or BTC_USDT for gate')
    ap.add_argument('--side', required=True, choices=['buy', 'sell'])
    ap.add_argument('--type', default='market', choices=['market', 'limit'])
    ap.add_argument('--quantity', type=float, required=True)
    ap.add_argument('--price', type=float, default=None, help='limit price; defaults to bid/ask if maker')
    ap.add_argument('--tif', default='GTC', choices=['GTC', 'IOC', 'FOK'])
    ap.add_argument('--edge-bps', type=float, default=3.0, help='ex-ante edge estimate (bps)')
    ap.add_argument('--latency-ms', type=float, default=10.0)
    ap.add_argument('--config', default='configs/default.toml')
    ap.add_argument('--schema', default='configs/schema.json')
    ap.add_argument('--profile', default='', help='Apply named profile from config (e.g. local_low)')
    args = ap.parse_args()

    # Load config for completeness (convert to mutable dict for profile overlay)
    cfg_obj = load_config(config_path=args.config, schema_path=args.schema, enable_watcher=False)
    cfg = cfg_obj.as_dict()

    if args.profile:
        def _get_nested(d: dict, parts: list):
            cur = d
            for p in parts:
                if not isinstance(cur, dict) or p not in cur:
                    return None
                cur = cur[p]
            return cur

        def _set_nested(d: dict, parts: list, value):
            cur = d
            for p in parts[:-1]:
                if p not in cur or not isinstance(cur[p], dict):
                    cur[p] = {}
                cur = cur[p]
            cur[parts[-1]] = value

        def _find_best_split_and_set(base: dict, key: str, value):
            parts = key.split("_")
            for i in range(1, len(parts)):
                prefix = parts[:i]
                last = "_".join(parts[i:])
                nested = _get_nested(base, prefix)
                if nested is None:
                    continue
                _set_nested(base, prefix + [last], value)
                return ".".join(prefix + [last])
            base[key] = value
            return key

        def _recursive_merge(base: dict, overlay: dict) -> list:
            changes = []
            for k, v in overlay.items():
                if isinstance(v, dict):
                    if isinstance(base.get(k), dict):
                        changes.extend(_recursive_merge(base[k], v))
                    else:
                        base[k] = v
                        changes.append(k)
                else:
                    if k in base and not isinstance(base.get(k), dict):
                        if base.get(k) != v:
                            base[k] = v
                            changes.append(k)
                    else:
                        mapped = _find_best_split_and_set(base, k, v)
                        if mapped:
                            changes.append(mapped)
            return changes

        profiles = cfg.get('profile') or {}
        prof = profiles.get(args.profile)
        if prof is None:
            print(f"PROFILE: unknown profile {args.profile}")
            raise SystemExit(61)
        import copy
        before = copy.deepcopy(cfg)
        changed = _recursive_merge(cfg, prof)
        logdir = Path('logs')
        logdir.mkdir(parents=True, exist_ok=True)
        out_path = logdir / f"profile_{args.profile}.txt"
        with out_path.open('w', encoding='utf-8') as fh:
            fh.write(f"APPLIED PROFILE: {args.profile}\n")
            fh.write("CHANGED KEYS:\n")
            for p in changed:
                old = before
                for part in p.split('.'):
                    old = old.get(part, None) if isinstance(old, dict) else None
                new = cfg
                for part in p.split('.'):
                    new = new.get(part, None) if isinstance(new, dict) else None
                fh.write(f"- {p}: {old!r} -> {new!r}\n")
        print(f"PROFILE: applied {args.profile} -> {out_path}")

    http = StdlibHttpClient()

    # Adapters
    if args.exchange == 'binance':
        ex = BinanceExchange(api_key=args.api_key, api_secret=args.api_secret, http=http, futures=args.futures)
        norm_symbol = ex.normalize_symbol(args.symbol)
    else:
        ex = GateExchange(api_key=args.api_key, api_secret=args.api_secret, http=http)
        norm_symbol = args.symbol.replace('-', '_').upper()

    # Fetch book and form quote snapshot
    book = fetch_book(args.exchange, norm_symbol, futures=args.futures, http=http)
    if book.bid <= 0 or book.ask <= 0 or book.ask <= book.bid:
        raise SystemExit(f"invalid book for {norm_symbol}: bid={book.bid} ask={book.ask}")
    quote = QuoteSnapshot(bid_px=book.bid, ask_px=book.ask)

    # Router decision (no hazard model by default)
    router = Router()
    dec = router.decide(
        side=args.side,
        quote=quote,
        edge_bps_estimate=float(args.edge_bps),
        latency_ms=float(args.latency_ms),
        fill_features=None,
    )
    print(f"route={dec.route} E_maker={dec.e_maker_bps:.2f}bps E_taker={dec.e_taker_bps:.2f}bps p_fill={dec.p_fill:.2f} reason='{dec.reason}'")

    if dec.route == 'deny':
        print('Decision: DENY — no order placed')
        return

    # Build order request
    side = Side.BUY if args.side.lower() == 'buy' else Side.SELL
    tif = TimeInForce[args.tif]

    if dec.route == 'taker' or args.type.lower() == 'market':
        req = OrderRequest(symbol=norm_symbol, side=side, type=OrderType.MARKET, quantity=float(args.quantity))
    else:
        # maker: choose price at best bid (buy) / best ask (sell) unless provided
        price = args.price
        if price is None:
            price = book.bid if side == Side.BUY else book.ask
        req = OrderRequest(symbol=norm_symbol, side=side, type=OrderType.LIMIT, quantity=float(args.quantity), price=float(price), tif=tif)

    # Place order via adapter (validates quantization/filters inside)
    res = ex.place_order(req)
    print(f"placed: order_id={res.order_id} client_id={res.client_order_id} status={res.status} executed={res.executed_qty}")


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
