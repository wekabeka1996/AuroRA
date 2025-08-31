from __future__ import annotations

import random
import time
from typing import Dict, Any, Optional, Callable

from core.aurora_event_logger import AuroraEventLogger


class SimLocalSink:
    """Simulated local execution sink.

    Provides submit/cancel/amend/on_tick and emits ORDER_STATUS(sim) XAI events.
    Designed for determinism via optional seed and test-friendly time_func/event collector.
    """

    def __init__(
        self,
        cfg: Optional[Dict[str, Any]] = None,
        ev: Optional[AuroraEventLogger] = None,
        time_func: Optional[Callable[[], float]] = None,
    ) -> None:
        cfg = cfg or {}
        self.cfg = cfg
        sim = cfg.get('order_sink', {}).get('sim_local', {})
        self.post_only = bool(sim.get('post_only', True))
        self.ioc = bool(sim.get('ioc', True))
        self.latency_ms_range = tuple(sim.get('latency_ms_range', [8, 25]))
        self.slip_bps_range = tuple(sim.get('slip_bps_range', [0.0, 1.2]))
        self.ttl_ms = int(sim.get('ttl_ms', 1500))
        self.maker_queue_model = sim.get('maker', {}).get('queue_model', 'depth_l1')
        self.maker_eps = float(sim.get('maker', {}).get('queue_safety_eps', 1e-6))
        self.taker_max_levels = int(sim.get('taker', {}).get('max_levels', 1))

        seed = sim.get('seed', None)
        if seed is None:
            self.rng = random.Random()
            self.rng_seed = None
        else:
            self.rng = random.Random(int(seed))
            self.rng_seed = int(seed)

        # Event logger (test injection)
        self._ev = ev or AuroraEventLogger()

        # time function (ms)
        self._time = time_func or (lambda: int(time.time() * 1000))

        # internal orders store
        self._orders: Dict[str, Dict[str, Any]] = {}

        # emitted rng seed flag
        self._seed_emitted = False

    def _sample_latency(self) -> int:
        a, b = self.latency_ms_range
        return int(self.rng.randint(a, b))

    def _sample_slip(self) -> float:
        a, b = self.slip_bps_range
        return float(self.rng.uniform(a, b))

    def _emit_seed_if_needed(self, details: Dict[str, Any]) -> None:
        if not self._seed_emitted and self.rng_seed is not None:
            details['rng_seed'] = self.rng_seed
            self._seed_emitted = True

    def submit(self, order: Dict[str, Any], market: Optional[Dict[str, Any]] = None) -> str:
        oid = order.get('order_id') or f"sim-{int(self._time())}-{self.rng.randint(0, 9999)}"
        o = dict(order)
        o['order_id'] = oid
        o['created_ts_ms'] = int(self._time())
        o['orig_qty'] = float(o.get('qty', 0))
        o['remaining'] = float(o.get('qty', 0))
        o['order_type'] = o.get('order_type', 'limit')
        self._orders[oid] = o

        # simulate immediate taker if market order or if liquidity crosses
        latency_action = self._sample_latency()
        latency_fill = None
        slip = None

        # obtain market snapshot if provided else empty
        m = market or {}
        bid = m.get('best_bid')
        ask = m.get('best_ask')
        # simple liquidity model: m['liquidity'] = {'bid': qty, 'ask': qty}
        liq = m.get('liquidity', {})

        # Decide taker vs maker behavior
        is_taker_action = False
        crossing = False
        if o['order_type'] == 'market':
            is_taker_action = True
        else:
            # limit order: determine crossing against top of book
            if o.get('side') == 'buy' and ask is not None and o.get('price') is not None and o.get('price') >= ask:
                crossing = True
            if o.get('side') == 'sell' and bid is not None and o.get('price') is not None and o.get('price') <= bid:
                crossing = True
            # post-only should reject crossing orders
            if self.post_only and crossing:
                evt = {
                    'order_id': oid,
                    'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                    'side': o.get('side'),
                    'px': o.get('price'),
                    'qty': o['orig_qty'],
                    'status': 'rejected',
                    'reason': 'post_only_cross',
                    'latency_ms_action': latency_action,
                    'latency_ms_fill': None,
                    'maker_queue_pos': None,
                    'fill_qty_step': 0.0,
                    'fill_ratio': 0.0,
                    'slip_bps': None,
                    'ttl_ms': self.ttl_ms,
                }
                self._emit_seed_if_needed(evt)
                self._ev.emit('ORDER_STATUS(sim)', evt)
                del self._orders[oid]
                return oid
            # if crossing and IOC or not post_only, treat as taker
            if crossing and self.ioc:
                is_taker_action = True

        if is_taker_action:
            # compute available opposite liquidity up to max_levels
            if o.get('side') == 'buy':
                avail = float(liq.get('ask', 0))
                ref_px = ask
            else:
                avail = float(liq.get('bid', 0))
                ref_px = bid

            fill_qty = min(o['remaining'], avail)
            slip = self._sample_slip()
            if fill_qty <= 0:
                # no liquidity
                if self.ioc:
                    status = 'rejected'
                    reason = 'ioc_no_liquidity'
                    evt = {
                        'order_id': oid,
                        'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                        'side': o.get('side'),
                        'px': None,
                        'qty': o['orig_qty'],
                        'status': status,
                        'reason': reason,
                        'latency_ms_action': latency_action,
                        'latency_ms_fill': None,
                        'maker_queue_pos': None,
                        'fill_qty_step': 0.0,
                        'fill_ratio': 0.0,
                        'slip_bps': slip,
                        'ttl_ms': self.ttl_ms,
                    }
                    self._emit_seed_if_needed(evt)
                    self._ev.emit('ORDER_STATUS(sim)', evt)
                    del self._orders[oid]
                    return oid
                else:
                    # leave as ack
                    status = 'new'
                    reason = None
                    evt = {
                        'order_id': oid,
                        'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                        'side': o.get('side'),
                        'px': None,
                        'qty': o['orig_qty'],
                        'status': status,
                        'reason': reason,
                        'latency_ms_action': latency_action,
                        'latency_ms_fill': None,
                        'maker_queue_pos': None,
                        'fill_qty_step': 0.0,
                        'fill_ratio': 0.0,
                        'slip_bps': None,
                        'ttl_ms': self.ttl_ms,
                    }
                    self._emit_seed_if_needed(evt)
                    self._ev.emit('ORDER_STATUS(sim)', evt)
                    return oid

            # compute fill price
            if ref_px is None:
                fill_px = None
            else:
                if o.get('side') == 'buy':
                    fill_px = ref_px * (1.0 + slip / 10000.0)
                else:
                    fill_px = ref_px * (1.0 - slip / 10000.0)

            # emit filled event
            latency_fill = self._sample_latency()
            evt = {
                'order_id': oid,
                'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                'side': o.get('side'),
                'px': fill_px,
                'qty': fill_qty,
                'status': 'filled',
                'reason': None,
                'latency_ms_action': latency_action,
                'latency_ms_fill': latency_fill,
                'maker_queue_pos': None,
                'fill_qty_step': fill_qty,
                'fill_ratio': float(fill_qty) / max(1e-9, o['orig_qty']),
                'slip_bps': slip,
                'ttl_ms': self.ttl_ms,
            }
            # tca: compute IS as spread component for simplicity
            mid = None
            if bid is not None and ask is not None and fill_px is not None:
                mid = (bid + ask) / 2.0
                is_bps = ((fill_px - mid) / mid) * 10000.0 if mid else 0.0
                evt['tca_breakdown'] = {
                    'Spread_bps': is_bps,
                    'Latency_bps': 0.0,
                    'Adverse_bps': 0.0,
                    'Impact_bps': 0.0,
                    'Fees_bps': 0.0,
                }

            self._emit_seed_if_needed(evt)
            self._ev.emit('ORDER_STATUS(sim)', evt)
            # remove order
            del self._orders[oid]
            return oid

        # Fallback: ack
        evt = {
            'order_id': oid,
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
            'side': o.get('side'),
            'px': o.get('price'),
            'qty': o['orig_qty'],
            'status': 'new',
            'reason': None,
            'latency_ms_action': latency_action,
            'latency_ms_fill': None,
            'maker_queue_pos': 0,
            'fill_qty_step': 0.0,
            'fill_ratio': 0.0,
            'slip_bps': None,
            'ttl_ms': self.ttl_ms,
        }
        self._emit_seed_if_needed(evt)
        self._ev.emit('ORDER_STATUS(sim)', evt)
        return oid

    def cancel(self, order_id: str) -> bool:
        if order_id not in self._orders:
            return False
        latency = self._sample_latency()
        evt = {
            'order_id': order_id,
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
            'side': self._orders[order_id].get('side'),
            'px': None,
            'qty': 0.0,
            'status': 'cancelled',
            'reason': 'cancelled_by_user',
            'latency_ms_action': latency,
            'latency_ms_fill': None,
            'maker_queue_pos': None,
            'fill_qty_step': 0.0,
            'fill_ratio': 0.0,
            'slip_bps': None,
            'ttl_ms': self.ttl_ms,
        }
        self._emit_seed_if_needed(evt)
        self._ev.emit('ORDER_STATUS(sim)', evt)
        del self._orders[order_id]
        return True

    def amend(self, order_id: str, fields: Dict[str, Any]) -> bool:
        if order_id not in self._orders:
            return False
        self._orders[order_id].update(fields)
        latency = self._sample_latency()
        evt = {
            'order_id': order_id,
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
            'side': self._orders[order_id].get('side'),
            'px': self._orders[order_id].get('price'),
            'qty': self._orders[order_id].get('remaining'),
            'status': 'replaced',
            'reason': None,
            'latency_ms_action': latency,
            'latency_ms_fill': None,
            'maker_queue_pos': None,
            'fill_qty_step': 0.0,
            'fill_ratio': 0.0,
            'slip_bps': None,
            'ttl_ms': self.ttl_ms,
        }
        self._emit_seed_if_needed(evt)
        self._ev.emit('ORDER_STATUS(sim)', evt)
        return True

    def on_tick(self, market_snapshot: Dict[str, Any]) -> None:
        # Iterate over orders and perform maker partial fills if applicable
        for oid, o in list(self._orders.items()):
            if o.get('order_type') != 'limit':
                continue
            # compute queue_ahead
            if self.maker_queue_model == 'depth_l1':
                queue_ahead = market_snapshot.get('depth', {}).get('at_price', {}).get(o.get('price'), 0.0)
            else:
                queue_ahead = market_snapshot.get('depth', {}).get('levels_sum', {}).get(o.get('price'), 0.0)
            traded = market_snapshot.get('traded_since_last', {}).get(o.get('price'), 0.0)
            eps = self.maker_eps
            denom = queue_ahead + o.get('remaining', 0.0) + eps
            p_fill = max(0.0, min(1.0, float(traded) / denom))
            fill_qty = round(o.get('remaining', 0.0) * p_fill, 8)
            if fill_qty <= 0:
                # check TTL
                age = int(self._time()) - int(o.get('created_ts_ms', 0))
                if age > self.ttl_ms:
                    evt = {
                        'order_id': oid,
                        'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                        'side': o.get('side'),
                        'px': o.get('price'),
                        'qty': o.get('remaining'),
                        'status': 'cancelled',
                        'reason': 'ttl_expired',
                        'latency_ms_action': self._sample_latency(),
                        'latency_ms_fill': None,
                        'maker_queue_pos': None,
                        'fill_qty_step': 0.0,
                        'fill_ratio': 0.0,
                        'slip_bps': None,
                        'ttl_ms': self.ttl_ms,
                    }
                    self._emit_seed_if_needed(evt)
                    self._ev.emit('ORDER_STATUS(sim)', evt)
                    del self._orders[oid]
                continue
            # apply partial fill
            o['remaining'] = max(0.0, o.get('remaining', 0.0) - fill_qty)
            latency_fill = self._sample_latency()
            evt = {
                'order_id': oid,
                'ts': time.strftime('%Y-%m-%dT%H:%M:%S') + 'Z',
                'side': o.get('side'),
                'px': o.get('price'),
                'qty': fill_qty,
                'status': 'partial' if o['remaining'] > 0 else 'filled',
                'reason': None,
                'latency_ms_action': self._sample_latency(),
                'latency_ms_fill': latency_fill,
                'maker_queue_pos': 0,
                'fill_qty_step': fill_qty,
                'fill_ratio': (o.get('orig_qty') - o.get('remaining', 0.0)) / max(1e-9, o.get('orig_qty')),
                'slip_bps': None,
                'ttl_ms': self.ttl_ms,
            }
            self._emit_seed_if_needed(evt)
            self._ev.emit('ORDER_STATUS(sim)', evt)
            if o['remaining'] <= 0:
                del self._orders[oid]
            
