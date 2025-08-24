
import os, time, yaml, math, statistics, numpy as np
from skalp_bot.exch.ccxt_binance import CCXTBinanceAdapter
from skalp_bot.core.signals import (
    micro_price, obi_from_l5, tfi_from_trades,
    ofi_simplified, absorption, sweep_score, liquidity_ahead,
    RollingPerc, compute_alpha_score,
)
from skalp_bot.core.ta import atr_wilder
from skalp_bot.risk.manager import RiskManager
from skalp_bot.integrations.aurora_gate import AuroraGate

def load_cfg(path='configs/default.yaml'):
    with open(path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)

def rolling_vol_bps(series, window=60):
    if len(series) < 2:
        return 0.0
    w = series[-window:] if len(series) >= window else series[:]
    if len(w) < 2:
        return 0.0
    try:
        std = statistics.pstdev(w)
        mid = w[-1] if w[-1] else 1.0
        return float(abs(std / mid) * 1e4)
    except Exception:
        return 0.0

def main(cfg_path: str | None = None):
    # Resolve default config relative to this file to avoid CWD issues
    if not cfg_path:
        base_dir = os.path.dirname(os.path.dirname(__file__))
        cfg_path = os.path.join(base_dir, 'configs', 'default.yaml')
    elif not os.path.isabs(cfg_path):
        # keep relative path as-is if explicitly provided but not absolute
        cfg_path = cfg_path
    cfg = load_cfg(cfg_path)
    ex = CCXTBinanceAdapter(cfg)
    risk = RiskManager(cfg)

    alpha = cfg['alpha']
    exe  = cfg['execution']
    aur  = cfg.get('aurora', {'enabled': True, 'base_url': 'http://127.0.0.1:8000', 'mode': os.getenv('AURORA_MODE', 'shadow')})
    clk  = cfg.get('clock_gate', { 'enabled': True, 'windows_sec': [[20,90],[420,510],[840,870]] })

    gate = AuroraGate(base_url=aur.get('base_url', 'http://127.0.0.1:8000'), mode=aur.get('mode', 'shadow'))
    order_size = float(exe.get('order_size', 0.001))
    fees_bps   = float(exe.get('fees_bps', 1.0))

    print(f"[WiseScalp x Aurora] start — dry_run={cfg.get('dry_run', True)} mode={aur.get('mode','shadow')} symbol={cfg.get('symbol')}" )

    mids = []
    atr_buffer = []  # store last 60 mids for 1m ATR proxy
    obi_hist = []    # for persistence over ~3s
    pos_side = None   # 'LONG' | 'SHORT' | None
    pos_qty  = 0.0
    entry_mid = None
    entry_ts = None
    # Local rate-limit (per minute) and exposure mirror
    trades_pm_limit = int(cfg.get('execution',{}).get('trades_per_minute_limit', 10))
    max_symbol_expo = float(cfg.get('execution',{}).get('max_symbol_exposure_usdt', 1000.0))
    recent_trades_ts = []  # timestamps (seconds)

    # Rolling percentiles per feature for robust normalization
    roll = {
        'OBI': RollingPerc(window=600),
        'TFI': RollingPerc(window=600),
        'ABSORB': RollingPerc(window=600),
        'MICRO_BIAS': RollingPerc(window=600),
        'OFI': RollingPerc(window=600),
        'TREND_ALIGN': RollingPerc(window=600),
    }

    # Trend state (EMA of 1s returns)
    ret_ema_15 = 0.0
    ret_ema_60 = 0.0
    ema15_alpha = 2.0 / (15.0 + 1.0)
    ema60_alpha = 2.0 / (60.0 + 1.0)
    prev_mid_for_ret = None

    # OFI previous quotes
    prev_best_bid = None
    prev_best_ask = None

    # ATR state and OHLCV cache
    atr_val = None
    last_ohlcv_ts = 0
    last_ohlcv_fetch = 0.0
    # Warmup OHLCV on start
    try:
        ohlcv = ex.fetch_ohlcv_1m(limit=200)
        if ohlcv:
            highs = [float(x[2]) for x in ohlcv]
            lows = [float(x[3]) for x in ohlcv]
            closes = [float(x[4]) for x in ohlcv]
            atr_val = atr_wilder(highs, lows, closes, period=14)
            last_ohlcv_ts = int(ohlcv[-1][0])
            last_ohlcv_fetch = time.time()
    except Exception:
        atr_val = None

    # OCO prices and reversal tracking
    tp_price = None
    sl_price = None
    reverse_count = 0

    def build_account_state():
        try:
            gross = 0.0
            positions = []
            if hasattr(ex, 'get_gross_exposure_usdt'):
                gross = float(ex.get_gross_exposure_usdt() or 0.0)
            if hasattr(ex, 'get_positions'):
                positions = ex.get_positions() or []
            return {"gross_exposure_usdt": gross, "positions": positions}
        except Exception:
            return {"gross_exposure_usdt": 0.0, "positions": []}

    tick_id = 0
    last_scores = []
    while True:
        # Fetch market snapshot
        mid, spread, bids, asks, trades = ex.fetch_top_of_book()
        mids.append(float(mid))

        # Top of book tuples
        best_bid = (float(bids[0][0]), float(bids[0][1]))
        best_ask = (float(asks[0][0]), float(asks[0][1]))

        # Core signals
        mp = micro_price(best_bid, best_ask)
        obi = obi_from_l5([(float(p), float(q)) for p, q in bids], [(float(p), float(q)) for p, q in asks], alpha['obi_levels'])
        tfi = tfi_from_trades(trades)

        # Volatility (1m realized bps)
        vol_bps = rolling_vol_bps(mids, window=60)

        # OBI persistence over last ~3s (keep last 5 samples)
        obi_hist.append(float(obi) if obi is not None else 0.0)
        if len(obi_hist) > 5:
            obi_hist = obi_hist[-5:]
        thr = 0.20
        obi_persist = float(sum(1 for v in obi_hist if v >= thr) / len(obi_hist)) if obi_hist else 0.0
        obi_persist_neg = float(sum(1 for v in obi_hist if v <= -thr) / len(obi_hist)) if obi_hist else 0.0

        # Sweep and liquidity ahead
        sw = sweep_score(trades)
        la_ask = liquidity_ahead(asks, levels=5)
        la_bid = liquidity_ahead(bids, levels=5)

        # Update OHLCV (rate-limited) and ATR (batch mode)
        now_ts = time.time()
        if (now_ts - last_ohlcv_fetch) >= 15.0:
            try:
                ohlcv = ex.fetch_ohlcv_1m(limit=100)
                if ohlcv:
                    ts_last = int(ohlcv[-1][0])
                    if ts_last != last_ohlcv_ts:
                        highs = [float(x[2]) for x in ohlcv]
                        lows = [float(x[3]) for x in ohlcv]
                        closes = [float(x[4]) for x in ohlcv]
                        atr_val = atr_wilder(highs, lows, closes, period=14)
                        last_ohlcv_ts = ts_last
                last_ohlcv_fetch = now_ts
            except Exception:
                pass

        # 15m clock-gate windows from config
        t_in_bar = int(time.time()) % 900
        clock_ok = False
        if bool(clk.get('enabled', True)):
            for w in clk.get('windows_sec', []):
                try:
                    lo, hi = int(w[0]), int(w[1])
                    if lo <= t_in_bar <= hi:
                        clock_ok = True
                        break
                except Exception:
                    continue
        else:
            clock_ok = True

        # Features for WS-α-02
        # MICRO_BIAS already computed; guard spread zero
        micro_bias = float((mp - mid) / (spread if spread else (mid * 1e-6))) if (mp is not None and mid) else 0.0
        # OFI uses previous best quotes
        ofi_val = 0.0
        if prev_best_bid is not None and prev_best_ask is not None:
            ofi_raw = ofi_simplified(prev_best_bid, prev_best_ask, best_bid, best_ask)
            ofi_val = float(ofi_raw or 0.0)
        # Absorption on both sides over ~3s
        absorb_bid = absorption(trades, side='bid', window_s=3.0)
        absorb_ask = absorption(trades, side='ask', window_s=3.0)
        # Normalize absorption to [-1,1] by difference/total
        absorb_norm = 0.0
        denom_abs = (absorb_bid + absorb_ask)
        if denom_abs > 0:
            absorb_norm = float((absorb_bid - absorb_ask) / denom_abs)
        # Trend alignment via EMA of 1s returns (sign average of short/long windows)
        if prev_mid_for_ret is not None and prev_mid_for_ret > 0:
            ret = (mid - prev_mid_for_ret) / prev_mid_for_ret
            ret_ema_15 = (1 - ema15_alpha) * ret_ema_15 + ema15_alpha * ret
            ret_ema_60 = (1 - ema60_alpha) * ret_ema_60 + ema60_alpha * ret
        prev_mid_for_ret = mid
        s15 = 1.0 if ret_ema_15 > 0 else (-1.0 if ret_ema_15 < 0 else 0.0)
        s60 = 1.0 if ret_ema_60 > 0 else (-1.0 if ret_ema_60 < 0 else 0.0)
        trend_align = 0.5 * (s15 + s60)

        features = {
            'OBI': float(obi) if obi is not None else 0.0,
            'TFI': float(tfi) if tfi is not None else 0.0,
            'ABSORB': absorb_norm,
            'MICRO_BIAS': float(micro_bias),
            'OFI': float(ofi_val),
            'TREND_ALIGN': float(trend_align),
        }

        # Update rolling percentiles and build rp dict
        rp = {}
        for k, v in features.items():
            rp[k] = roll[k].update(v)

        # Compute normalized alpha score
        weights = alpha.get('weights') if isinstance(alpha, dict) else None
        score = compute_alpha_score(features, rp, weights=weights)
        last_scores.append(score)
        if len(last_scores) > 10:
            last_scores = last_scores[-10:]
        market = {
            'mid': mid,
            'spread_bps': float(spread / mid * 1e4 if mid else 0.0),
            'obi_l5': float(obi) if obi is not None else 0.0,
            'tfi_5s': float(tfi) if tfi is not None else 0.0,
            'vol_1m_bps': vol_bps,
            'rv_1m_bps': vol_bps,
            'funding_rate': 0.0,
            'sweep_score': float(sw),
            'liquidity_ahead_ask': float(la_ask),
            'liquidity_ahead_bid': float(la_bid),
            'micro_bias': float(micro_bias),
            'obi_persist_3s': float(obi_persist),
            'ofi_5s': float(ofi_val),
            'absorb_bid': float(absorb_bid),
            'absorb_ask': float(absorb_ask),
        }

        # TRAP guard + OBI/TFI consensus
        trap_flag = False
        if obi is not None and tfi is not None:
            cond1 = (abs(obi) >= 0.2)
            cond2 = (np.sign(obi) != np.sign(tfi))
            cond3 = (abs(tfi) >= 0.1)
            if (cond1 + cond2 + cond3) >= 2:
                trap_flag = True
        market['trap_flag'] = trap_flag

        consensus_ok_long = (obi is not None and tfi is not None and (obi >= +0.20) and (tfi >= +0.10))
        consensus_ok_short = (obi is not None and tfi is not None and (obi <= -0.20) and (tfi <= -0.10))

        # Entry/exit logic
        side: str | None = None
        entry_thr = 0.35
        exit_thr = 0.05
        if pos_side is None:
            # hard spread guard
            spread_limit = float(exe.get('spread_guard_bps_max', 8))
            if market['spread_bps'] > spread_limit:
                print(f"[SKIP] reason=spread_guard spread_bps={market['spread_bps']:.1f} limit={spread_limit}")
            else:
                if score >= entry_thr:
                    side = 'LONG'
                elif score <= -entry_thr:
                    side = 'SHORT'
        else:
            # soft exit when score magnitude small
            if abs(score) < exit_thr:
                close_qty = pos_qty
                em = entry_mid if entry_mid is not None else mid
                pnl_usdt = (mid - em) * close_qty * (1 if pos_side == 'LONG' else -1)
                gate.posttrade(
                    ts_close=int(time.time() * 1000),
                    req_id=f"rq-{int(time.time()*1e6)}",
                    symbol=ex.symbol.replace('/', ''),
                    side=pos_side,
                    qty=float(close_qty),
                    price_open=float(em),
                    price_close=float(mid),
                    fees_usdt=float(abs(close_qty) * mid * (fees_bps / 1e4)),
                    slippage_bps=float(abs(mid - em) / (mid if mid else 1.0) * 1e4),
                    pnl_usdt=float(pnl_usdt),
                    reason="signal_exit",
                )
                pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                tp_price, sl_price = None, None

        # OCO checks, Time-stop and reversal
        if pos_side is not None:
            nowt = time.time()
            # Compute ATR used (or proxy) for exit logic
            atr_used = atr_val if atr_val is not None else (mid * (vol_bps / 1e4) if mid else None)
            # OCO TP/SL
            if tp_price is not None and sl_price is not None:
                if pos_side == 'LONG':
                    if mid >= tp_price:
                        em = entry_mid if entry_mid is not None else mid
                        pnl_usdt = (mid - em) * pos_qty
                        gate.posttrade(
                            ts_close=int(time.time() * 1000),
                            req_id=f"rq-{int(time.time()*1e6)}",
                            symbol=ex.symbol.replace('/', ''),
                            side=pos_side,
                            qty=float(pos_qty),
                            price_open=float(em),
                            price_close=float(mid),
                            fees_usdt=float(abs(pos_qty) * mid * (fees_bps / 1e4)),
                            slippage_bps=0.0,
                            pnl_usdt=float(pnl_usdt),
                            reason="tp",
                        )
                        pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                        tp_price, sl_price = None, None
                    elif mid <= sl_price:
                        em = entry_mid if entry_mid is not None else mid
                        pnl_usdt = (mid - em) * pos_qty
                        gate.posttrade(
                            ts_close=int(time.time() * 1000),
                            req_id=f"rq-{int(time.time()*1e6)}",
                            symbol=ex.symbol.replace('/', ''),
                            side=pos_side,
                            qty=float(pos_qty),
                            price_open=float(em),
                            price_close=float(mid),
                            fees_usdt=float(abs(pos_qty) * mid * (fees_bps / 1e4)),
                            slippage_bps=0.0,
                            pnl_usdt=float(pnl_usdt),
                            reason="sl",
                        )
                        pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                        tp_price, sl_price = None, None
                elif pos_side == 'SHORT':
                    if mid <= tp_price:
                        em = entry_mid if entry_mid is not None else mid
                        pnl_usdt = (em - mid) * pos_qty
                        gate.posttrade(
                            ts_close=int(time.time() * 1000),
                            req_id=f"rq-{int(time.time()*1e6)}",
                            symbol=ex.symbol.replace('/', ''),
                            side=pos_side,
                            qty=float(pos_qty),
                            price_open=float(em),
                            price_close=float(mid),
                            fees_usdt=float(abs(pos_qty) * mid * (fees_bps / 1e4)),
                            slippage_bps=0.0,
                            pnl_usdt=float(pnl_usdt),
                            reason="tp",
                        )
                        pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                        tp_price, sl_price = None, None
                    elif mid >= sl_price:
                        em = entry_mid if entry_mid is not None else mid
                        pnl_usdt = (em - mid) * pos_qty
                        gate.posttrade(
                            ts_close=int(time.time() * 1000),
                            req_id=f"rq-{int(time.time()*1e6)}",
                            symbol=ex.symbol.replace('/', ''),
                            side=pos_side,
                            qty=float(pos_qty),
                            price_open=float(em),
                            price_close=float(mid),
                            fees_usdt=float(abs(pos_qty) * mid * (fees_bps / 1e4)),
                            slippage_bps=0.0,
                            pnl_usdt=float(pnl_usdt),
                            reason="sl",
                        )
                        pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                        tp_price, sl_price = None, None
            # time-stop 90s
            if entry_ts and (nowt - entry_ts >= 90):
                em = entry_mid if entry_mid is not None else mid
                pnl_usdt = (mid - em) * pos_qty * (1 if pos_side == 'LONG' else -1)
                if (atr_used is None) or (pnl_usdt < (0.2 * atr_used * pos_qty)):
                    gate.posttrade(
                        ts_close=int(time.time() * 1000),
                        req_id=f"rq-{int(time.time()*1e6)}",
                        symbol=ex.symbol.replace('/', ''),
                        side=pos_side,
                        qty=float(pos_qty),
                        price_open=float(em),
                        price_close=float(mid),
                        fees_usdt=float(abs(pos_qty) * mid * (fees_bps / 1e4)),
                        slippage_bps=0.0,
                        pnl_usdt=float(pnl_usdt),
                        reason="time_stop_90s",
                    )
                    pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                    tp_price, sl_price = None, None
            else:
                # reversal: if score crosses to opposite side 2-3 ticks
                desired_sign = 1.0 if pos_side == 'SHORT' else -1.0  # opposite sign to current position
                if (score > 0 and desired_sign > 0) or (score < 0 and desired_sign < 0):
                    reverse_count += 1
                else:
                    reverse_count = 0
                if reverse_count >= 2:
                    em = entry_mid if entry_mid is not None else mid
                    pnl_usdt = (mid - em) * pos_qty * (1 if pos_side == 'LONG' else -1)
                    gate.posttrade(
                        ts_close=int(time.time() * 1000),
                        req_id=f"rq-{int(time.time()*1e6)}",
                        symbol=ex.symbol.replace('/', ''),
                        side=pos_side,
                        qty=float(pos_qty),
                        price_open=float(em),
                        price_close=float(mid),
                        fees_usdt=float(abs(pos_qty) * mid * (fees_bps / 1e4)),
                        slippage_bps=0.0,
                        pnl_usdt=float(pnl_usdt),
                        reason="reversal",
                    )
                    pos_side, pos_qty, entry_mid, entry_ts = None, 0.0, None, None
                    tp_price, sl_price = None, None

        # entry gating by time, trap, and OBI persistence
        skip_reason = None
        if side is not None:
            if not clock_ok:
                skip_reason = 'clock_no'
            elif trap_flag:
                skip_reason = 'trap'
            elif (side == 'LONG' and obi_persist < 0.66) or (side == 'SHORT' and obi_persist_neg < 0.66):
                skip_reason = 'obi_persist'
            # OBI/TFI consensus mandatory
            elif side == 'LONG' and not consensus_ok_long:
                skip_reason = 'consensus_long_fail'
            elif side == 'SHORT' and not consensus_ok_short:
                skip_reason = 'consensus_short_fail'
            # reconfirm on tick of open: use 2-s avg
            else:
                score_now = score
                score_avg_2s = float(sum(last_scores[-2:]) / max(1, len(last_scores[-2:])))
                if not ((score_now >= entry_thr if side=='LONG' else score_now <= -entry_thr) and (score_avg_2s >= entry_thr if side=='LONG' else score_avg_2s <= -entry_thr)):
                    skip_reason = 'reconfirm_fail'
        if skip_reason is not None:
            print(f"[SKIP] reason={skip_reason} side={side} score={score:+.3f} obi={obi} tfi={tfi} spread_bps={market['spread_bps']:.1f}")
            side = None

        # defaults for diagnostics
        local_limit_block = False
        gate_state = '-'
        gate_allow = True
        gate_max_qty = float('inf')
        gate_reason = '-'

        if side is not None:
            # local rate-limit per minute
            now_ts = time.time()
            recent_trades_ts = [t for t in recent_trades_ts if now_ts - t < 60.0]
            local_limit_block = len(recent_trades_ts) >= trades_pm_limit
            if local_limit_block:
                print(f"[LOCAL-LIMIT] trades/min limit reached: {len(recent_trades_ts)} >= {trades_pm_limit}")
                time.sleep(1.0)
                # skip placing a trade this tick
            else:
                # Build desired order
                order = {
                    'symbol': ex.symbol.replace('/', ''),
                    'side': side,
                    'type': 'LIMIT' if exe.get('maker_mode', True) else 'MARKET',
                    'price': float(bids[0][0] if side == 'LONG' else asks[0][0]) if exe.get('maker_mode', True) else None,
                    'qty': order_size,
                    'leverage': int(cfg.get('leverage', 10)),
                    'time_in_force': 'GTC',
                }
                account = build_account_state()
                # local exposure check
                price_val = order.get('price')
                price_val = float(mid) if price_val is None else float(price_val)
                est_expo = float(order['qty']) * float(price_val)
                if est_expo > max_symbol_expo:
                    print(f"[LOCAL-LIMIT] exposure limit: est={est_expo:.2f} > max={max_symbol_expo:.2f}")
                else:
                    # Pre-trade check
                    if aur.get('enabled', True):
                        resp = gate.check(account=account, order=order, market=market, risk_tags=("scalping", "auto"), fees_bps=fees_bps)
                        gate_state = resp.get('observability', {}).get('gate_state')
                        gate_allow = bool(resp.get('allow', True))
                        gate_max_qty = float(resp.get('max_qty', order['qty']))
                        gate_reason = resp.get('reason', '-')
                        if (not gate_allow) or resp.get('hard_gate', False):
                            print(f"[GATE] BLOCKED: reason={resp.get('reason')} state={resp.get('observability', {}).get('gate_state')}")
                        else:
                            # Adjust qty and apply cooldown
                            order['qty'] = min(order['qty'], gate_max_qty)
                            cd = float(resp.get('cooldown_ms', 0.0)) / 1000.0
                            if cd > 0:
                                time.sleep(cd)

                            # Place order (dry_run friendly in adapter)
                            # ATR guard: don't open if ATR unavailable
                            atr_used = atr_val if atr_val is not None else (mid * (vol_bps / 1e4) if mid else None)
                            if atr_used is None:
                                print("[GUARD] ATR unavailable, skip open")
                            else:
                                r = ex.place_order(side=('buy' if side == 'LONG' else 'sell'), qty=order['qty'], price=order.get('price'))
                                pos_side, pos_qty, entry_mid = side, order['qty'], mid
                                entry_ts = now_ts
                                # Compute ATR-based OCO
                                if side == 'LONG':
                                    tp_price = entry_mid + 1.2 * atr_used
                                    sl_price = entry_mid - 0.8 * atr_used
                                else:
                                    tp_price = entry_mid - 1.2 * atr_used
                                    sl_price = entry_mid + 0.8 * atr_used
                                print(f"[OCO] tp={tp_price:.2f} sl={sl_price:.2f} atr={atr_used:.2f}")
                                print(f"[TRADE] {side} qty={order['qty']} price={order.get('price')} resp={r}")
                                print(f"[ENTRY] side={side} score_now={score:+.3f} avg2s={float(sum(last_scores[-2:]) / max(1, len(last_scores[-2:]))):+.3f} obi={obi} tfi={tfi} spread={market['spread_bps']:.1f} reason=clock_open_reconfirm")
                                recent_trades_ts.append(now_ts)
                    else:
                        # Aurora disabled: keep defaults
                        pass

        # diagnostics: periodic LOB and gating state
        atr_used_dbg = atr_val if atr_val is not None else (mid * (vol_bps / 1e4) if mid else None)
        try:
            print(
                f"[DBG] t={time.strftime('%H:%M:%S')} CLOCK:{'OK' if clock_ok else 'NO'} SIB={t_in_bar} "
                f"ATR:{(f'{atr_used_dbg:.2f}' if atr_used_dbg else 'None')} "
                f"TRAP:{int(trap_flag)} LM:{int(len(recent_trades_ts) >= trades_pm_limit)} "
                f"GATE:{gate_state} allow={gate_allow} max_qty={(gate_max_qty if gate_max_qty!=float('inf') else 'inf')} reason={gate_reason} "
                f"OBI_p3s={obi_persist:.2f} MBias={micro_bias:.2f} spread_bps={market['spread_bps']:.1f}"
            )
        except Exception:
            pass
        if (tick_id % 30) == 0:
            try:
                sum_bid = sum(float(q) for _, q in bids[:5])
                sum_ask = sum(float(q) for _, q in asks[:5])
                print(f"[LOB] sumBidL5={sum_bid:.0f} sumAskL5={sum_ask:.0f} OBI={(obi if obi is not None else 0.0):.3f}")
            except Exception:
                pass

        # heartbeat
        try:
            print(f"mid={mid:.2f} score={score:+.3f} obi={obi} tfi={tfi} pos={pos_side or '-'}")
        except Exception:
            # mid or score might be None briefly; guard formatting
            print(f"mid={mid} score={score} pos={pos_side or '-'}")
        # Update previous quotes for OFI at end of tick
        prev_best_bid = best_bid
        prev_best_ask = best_ask
        tick_id += 1
        time.sleep(1.0)
