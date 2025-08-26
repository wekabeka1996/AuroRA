
import os, time, yaml, math, statistics, numpy as np, re, sys
from pathlib import Path
from core.aurora_event_logger import AuroraEventLogger
from core.ack_tracker import AckTracker
from skalp_bot.exch.ccxt_binance import CCXTBinanceAdapter
from skalp_bot.core.signals import (
    micro_price, obi_from_l5, tfi_from_trades,
    ofi_simplified, absorption, sweep_score, liquidity_ahead,
    RollingPerc, compute_alpha_score,
)
from skalp_bot.core.ta import atr_wilder
from skalp_bot.risk.manager import RiskManager
from skalp_bot.integrations.aurora_gate import AuroraGate

ROOT = Path(__file__).resolve().parents[2]

def _load_dotenv_if_present(env_path: Path) -> None:
    """Load simple KEY=VALUE pairs from .env if present; ignore comments and do not override existing env."""
    try:
        if not env_path.exists():
            return
        for line in env_path.read_text(encoding="utf-8").splitlines():
            m = re.match(r"^\s*([^#=]+)\s*=\s*(.*)\s*$", line)
            if not m:
                continue
            k, v = m.group(1).strip(), m.group(2).strip().strip('"').strip("'")
            # strip inline comments
            v = re.split(r"\s+#", v, maxsplit=1)[0].strip()
            if k and (k not in os.environ or not os.environ.get(k)):
                os.environ[k] = v
        # sanitize EXCHANGE_ID if it had quotes or inline comments
        ex = os.getenv("EXCHANGE_ID")
        if ex is not None:
            ex2 = re.split(r"\s+#", ex.strip().strip('"').strip("'"), maxsplit=1)[0].strip()
            os.environ["EXCHANGE_ID"] = ex2
    except Exception:
        # best-effort; never crash on dotenv issues
        pass

def _print_masked_keys() -> None:
    ak = os.getenv('BINANCE_API_KEY')
    sk = os.getenv('BINANCE_API_SECRET')
    try:
        if ak and sk:
            print(f"✅ Keys present (masked): BINANCE_API_KEY=****{ak[-4:]} BINANCE_API_SECRET=****{sk[-4:]}")
        else:
            print("❌ BINANCE_API_KEY / BINANCE_API_SECRET missing — add to .env or environment for live orders (DRY_RUN=false)")
    except Exception:
        pass

def load_cfg(path: str | os.PathLike):
    """Load YAML config from a resolved path."""
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
    # Best-effort load .env from repo root to populate EXCHANGE_*, DRY_RUN, AURORA_* switches
    _load_dotenv_if_present(ROOT / '.env')
    # Safe defaults for testnet unless explicitly overridden
    os.environ.setdefault('EXCHANGE_TESTNET', 'true')
    os.environ.setdefault('EXCHANGE_USE_FUTURES', 'true')
    os.environ.setdefault('DRY_RUN', 'false')
    # Keep user-selected mode if provided; otherwise default to 'shadow' for safe startup
    os.environ.setdefault('AURORA_MODE', os.environ.get('AURORA_MODE', 'shadow'))
    _print_masked_keys()
    # Create per-session log directory if not provided
    sess_dir_env = os.getenv('AURORA_SESSION_DIR')
    if not sess_dir_env:
        stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
        sess_dir = Path('logs') / stamp
        try:
            sess_dir.mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        os.environ['AURORA_SESSION_DIR'] = str(sess_dir.resolve())
        print(f"[SESSION] logs dir = {os.environ['AURORA_SESSION_DIR']}")
    else:
        try:
            Path(sess_dir_env).mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
        print(f"[SESSION] logs dir = {sess_dir_env}")
    # Resolve config path robustly
    def _resolve_cfg(user_path: str | None) -> Path:
        # Candidate locations ordered by preference
        cfg_dir = Path(__file__).resolve().parent.parent / 'configs'
        candidates: list[Path] = []
        if user_path:
            p = Path(user_path)
            if p.is_absolute():
                candidates.append(p)
            else:
                # Try as given relative to CWD
                candidates.append(Path.cwd() / p)
                # Try relative to configs directory (full subpath support)
                candidates.append(cfg_dir / p)
        else:
            # No user path — try defaults inside configs
            candidates.append(cfg_dir / 'default.aurora.yaml')
            candidates.append(cfg_dir / 'default.yaml')
        for c in candidates:
            if c.exists():
                return c
        # Return first candidate; caller will raise with a clear error listing tried locations
        return candidates[0] if candidates else (cfg_dir / 'default.yaml')

    resolved_cfg = _resolve_cfg(cfg_path)
    if not resolved_cfg.exists():
        cfg_dir = Path(__file__).resolve().parent.parent / 'configs'
        if cfg_path:
            p = Path(cfg_path)
            if p.is_absolute():
                tried = [p]
            else:
                tried = [Path.cwd() / p, cfg_dir / p]
            raise FileNotFoundError(f"Config file not found. Tried: {', '.join(str(t) for t in tried)}")
        else:
            tried = [cfg_dir / 'default.aurora.yaml', cfg_dir / 'default.yaml']
            raise FileNotFoundError(f"No default config found. Tried: {', '.join(str(t) for t in tried)}")
    print(f"[CFG] using {resolved_cfg}")
    cfg = load_cfg(str(resolved_cfg))
    # Env-over-YAML precedence (minimal): DRY_RUN and AURORA_MODE
    def _env_bool(name: str, default: bool) -> bool:
        v = os.getenv(name)
        if v is None:
            return default
        return v.strip().lower() in ("1", "true", "yes", "on")
    cfg['dry_run'] = _env_bool('DRY_RUN', bool(cfg.get('dry_run', True)))
    aurora_cfg = cfg.get('aurora') or {}
    env_mode = os.getenv('AURORA_MODE')
    if env_mode:
        aurora_cfg['mode'] = env_mode
    cfg['aurora'] = aurora_cfg
    ex = CCXTBinanceAdapter(cfg)
    risk = RiskManager(cfg)

    alpha = cfg['alpha']
    exe  = cfg['execution']
    aur  = cfg.get('aurora', {'enabled': True, 'base_url': 'http://127.0.0.1:8000', 'mode': os.getenv('AURORA_MODE', 'shadow')})
    clk  = cfg.get('clock_gate', { 'enabled': True, 'windows_sec': [[20,90],[420,510],[840,870]] })

    # Observability emitter (canonical path inside session directory)
    sess_base = Path(os.getenv('AURORA_SESSION_DIR', 'logs'))
    emitter = AuroraEventLogger(path=sess_base / 'aurora_events.jsonl')
    # Ack/Expire tracker wired to emitter
    ack_tracker = AckTracker(events_emit=lambda code, d: emitter.emit(code, d), ttl_s=int(os.getenv('AURORA_ACK_TTL_S', '300')), scan_period_s=1)

    # Env overrides
    def _as_bool(x: str | None) -> bool:
        if x is None:
            return False
        v = x.strip().lower()
        return v in ("1", "true", "yes", "on")

    is_testnet = _as_bool(os.getenv('EXCHANGE_TESTNET', 'false'))
    clock_env = os.getenv('CLOCK_GUARD') or os.getenv('AURORA_CLOCK_GUARD')
    if clock_env is not None and clock_env.strip().lower() in ("off", "0", "false", "no"):
        clk['enabled'] = False

    # Configure HTTP timeout for Aurora gate (default 100ms)
    try:
        _http_to_ms = int(os.getenv('AURORA_HTTP_TIMEOUT_MS', '100'))
    except Exception:
        _http_to_ms = 100
    gate = AuroraGate(
        base_url=aur.get('base_url', 'http://127.0.0.1:8000'),
        mode=aur.get('mode', 'shadow'),
        timeout_s=max(0.01, float(_http_to_ms) / 1000.0),
    )
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
    # rolling window of chosen spread (for adaptive limit on testnet)
    spread_window: list[float] = []

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
        # Compute raw top-of-book spread and effective spread (testnet only)
        spread_bps_raw = float(spread / mid * 1e4 if mid else 0.0)

        def _vwap_for_base_qty(base_qty: float, side: str) -> float:
            # Walk top-3 levels to get average execution price for base quantity
            if base_qty <= 0:
                return float('nan')
            book = asks if side == 'buy' else bids
            remaining = base_qty
            paid_quote = 0.0
            filled_base = 0.0
            for p, q in book[:3]:
                p = float(p); q = float(q)
                if p <= 0 or q <= 0:
                    continue
                take_base = min(q, remaining)
                paid_quote += take_base * p
                filled_base += take_base
                remaining -= take_base
                if remaining <= 1e-12:
                    break
            if filled_base <= 0:
                return float('nan')
            return paid_quote / filled_base

        order_size = float(exe.get('order_size', 0.001))
        px_buy = _vwap_for_base_qty(order_size, 'buy')
        px_sell = _vwap_for_base_qty(order_size, 'sell')
        eff_spread_bps = float(((px_buy - px_sell) / mid) * 1e4) if (mid and not math.isnan(px_buy) and not math.isnan(px_sell)) else spread_bps_raw
        chosen_spread_bps = eff_spread_bps if is_testnet else spread_bps_raw

        # Approximate ATR in bps to serve as symmetric a/b impact for expected-return gate
        if atr_val is not None and mid:
            try:
                atr_bps = float(atr_val / float(mid) * 1e4)
            except Exception:
                atr_bps = float(vol_bps)
        else:
            atr_bps = float(vol_bps)
        a_bps_est = max(2.0, min(150.0, float(atr_bps)))
        b_bps_est = a_bps_est
        # Slippage estimate as a fraction of effective (or raw) spread
        # Make the fraction configurable via env (use a safer lower default on testnet)
        try:
            _slip_frac_default = 0.25 if is_testnet else 0.50
            slip_frac = float(os.getenv('AURORA_SLIP_FRACTION', str(_slip_frac_default)))
        except Exception:
            slip_frac = 0.25 if is_testnet else 0.50
        slip_frac = max(0.0, min(1.0, float(slip_frac)))
        slip_bps_est = float(max(0.0, slip_frac * chosen_spread_bps))
        # Simple regime proxy from trend alignment
        mode_regime = ('trend_pos' if trend_align > 0 else ('trend_neg' if trend_align < 0 else 'normal'))

        market = {
            'mid': mid,
            'spread_bps': float(chosen_spread_bps),
            'spread_bps_raw': float(spread_bps_raw),
            'effective_spread_bps': float(eff_spread_bps),
            # expected-return inputs
            'score': float(score),
            'a_bps': float(a_bps_est),
            'b_bps': float(b_bps_est),
            'slip_bps_est': float(slip_bps_est),
            'mode_regime': mode_regime,
            'latency_ms': 5.0,  # local proxy; real inference latency is measured server-side
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
            # hard spread guard with env override and adaptive limit on testnet
            env_limit = os.getenv('AURORA_SPREAD_MAX_BPS')
            base_limit = float(env_limit) if (env_limit is not None and env_limit.strip()) else float(exe.get('spread_guard_bps_max', 8))
            # update rolling window
            spread_window.append(float(chosen_spread_bps))
            if len(spread_window) > 60:
                spread_window = spread_window[-60:]
            adapt_limit = base_limit
            if is_testnet and spread_window:
                try:
                    med = statistics.median(spread_window)
                    adapt_limit = max(base_limit, float(med * 2.0))
                except Exception:
                    adapt_limit = base_limit
            if market['spread_bps'] > adapt_limit:
                print(f"[SKIP] reason=spread_guard spread_bps={market['spread_bps']:.1f} limit={adapt_limit}")
                try:
                    emitter.emit(
                        "SPREAD_GUARD_TRIP",
                        {
                            "spread_bps_raw": float(spread_bps_raw),
                            "eff_spread_bps": float(eff_spread_bps),
                            "limit_bps": float(adapt_limit),
                            "top_of_book_spread_bps": float(spread_bps_raw),
                            "qty_base": float(order_size),
                            "testnet": bool(is_testnet),
                        },
                        src="runner",
                    )
                except Exception:
                    pass
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

        # entry pre-checks (hard) and post-checks (soft):
        # - Hard: clock/trap only — block before calling Aurora gate to avoid noise.
        # - Soft: obi_persist/consensus/reconfirm — applied AFTER gate, to decide order placement (but gate still gets called for observability).
        pre_skip_reason = None
        post_local_reason = None
        if side is not None:
            if not clock_ok:
                pre_skip_reason = 'clock_no'
            elif trap_flag:
                pre_skip_reason = 'trap'
            else:
                # collect soft reasons (do not prevent gate call)
                if (side == 'LONG' and obi_persist < 0.66) or (side == 'SHORT' and obi_persist_neg < 0.66):
                    post_local_reason = 'obi_persist'
                elif side == 'LONG' and not consensus_ok_long:
                    post_local_reason = 'consensus_long_fail'
                elif side == 'SHORT' and not consensus_ok_short:
                    post_local_reason = 'consensus_short_fail'
                else:
                    score_now = score
                    score_avg_2s = float(sum(last_scores[-2:]) / max(1, len(last_scores[-2:])))
                    ok_now = (score_now >= entry_thr) if side == 'LONG' else (score_now <= -entry_thr)
                    ok_avg = (score_avg_2s >= entry_thr) if side == 'LONG' else (score_avg_2s <= -entry_thr)
                    if not (ok_now and ok_avg):
                        post_local_reason = 'reconfirm_fail'
        if pre_skip_reason is not None:
            print(f"[SKIP] reason={pre_skip_reason} side={side} score={score:+.3f} obi={obi} tfi={tfi} spread_bps={market['spread_bps']:.1f}")
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
                        # enrich order with base_notional for risk
                        try:
                            order['base_notional'] = float(order['qty']) * float(price_val)
                        except Exception:
                            pass
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

                            # Post local filters: only place order if they pass; gate still executed for observability
                            if post_local_reason is not None:
                                print(f"[SKIP] reason={post_local_reason} side={side} score={score:+.3f} obi={obi} tfi={tfi} spread_bps={market['spread_bps']:.1f}")
                            else:
                                # Place order (dry_run friendly in adapter)
                                # ATR guard: don't open if ATR unavailable
                                atr_used = atr_val if atr_val is not None else (mid * (vol_bps / 1e4) if mid else None)
                                if atr_used is None:
                                    print("[GUARD] ATR unavailable, skip open")
                                else:
                                    # Generate client id and emit ORDER.SUBMIT
                                    cid = f"cid-{int(time.time()*1e6)}"
                                    order['cid'] = cid
                                    try:
                                        _pr = order.get('price')
                                        _pr_val = float(_pr) if _pr is not None else None
                                        emitter.emit(
                                            "ORDER.SUBMIT",
                                            {
                                                "symbol": ex.symbol.replace('/', ''),
                                                "cid": cid,
                                                "side": side,
                                                "order_type": ('LIMIT' if order.get('price') is not None else 'MARKET'),
                                                "price": _pr_val,
                                                "qty": float(order['qty']),
                                            },
                                            src="runner",
                                        )
                                        # Track submit for potential EXPIRE if ACK doesn't arrive in time
                                        try:
                                            emitter_ns = int(time.time() * 1_000_000_000)
                                        except Exception:
                                            emitter_ns = None
                                        try:
                                            ack_tracker.add_submit(symbol=ex.symbol.replace('/', ''), cid=cid, side=side, qty=float(order['qty']), t_submit_ns=emitter_ns)
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                    try:
                                        r = ex.place_order(
                                            side=('buy' if side == 'LONG' else 'sell'),
                                            qty=order['qty'],
                                            price=order.get('price'),
                                        )
                                    except Exception as e:
                                        # Emit ORDER.REJECT on error
                                        try:
                                            _pr = order.get('price')
                                            _pr_val = float(_pr) if _pr is not None else None
                                            emitter.emit(
                                                "ORDER.REJECT",
                                                {
                                                    "symbol": ex.symbol.replace('/', ''),
                                                    "cid": cid,
                                                    "side": side,
                                                    "order_type": ('LIMIT' if order.get('price') is not None else 'MARKET'),
                                                    "price": _pr_val,
                                                    "qty": float(order['qty']),
                                                    "error": str(e),
                                                },
                                                src="runner",
                                            )
                                        except Exception:
                                            pass
                                        raise
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
                                    # Emit ORDER.ACK after successful placement
                                    try:
                                        oid = None
                                        if isinstance(r, dict):
                                            info = r.get('info') or {}
                                            oid = r.get('id') or r.get('order_id') or info.get('orderId')
                                        _pr = order.get('price')
                                        _pr_val = float(_pr) if _pr is not None else None
                                        emitter.emit(
                                            "ORDER.ACK",
                                            {
                                                "symbol": ex.symbol.replace('/', ''),
                                                "cid": cid,
                                                "oid": oid,
                                                "side": side,
                                                "order_type": ('LIMIT' if order.get('price') is not None else 'MARKET'),
                                                "price": _pr_val,
                                                "qty": float(order['qty']),
                                            },
                                            src="runner",
                                        )
                                        # Clear from pending on ACK
                                        try:
                                            ack_tracker.ack(cid)
                                        except Exception:
                                            pass
                                    except Exception:
                                        pass
                                    # Log order open to posttrade endpoint for consolidated orders.jsonl
                                    try:
                                        po = order.get('price')
                                        po_val = float(po) if po is not None else (float(mid) if mid is not None else 0.0)
                                        gate.posttrade(
                                            ts_open=int(time.time() * 1000),
                                            req_id=f"rq-{int(time.time()*1e6)}",
                                            symbol=ex.symbol.replace('/', ''),
                                            side=side,
                                            qty=float(order['qty']),
                                            price_open=po_val,
                                            reason="open",
                                            response=r,
                                        )
                                    except Exception:
                                        pass
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
                f"OBI_p3s={obi_persist:.2f} MBias={micro_bias:.2f} spread_bps={market['spread_bps']:.1f} raw_spread_bps={spread_bps_raw:.1f} eff_spread_bps={eff_spread_bps:.1f}"
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
        # Periodic scan for expired submits without ACK
        try:
            if (tick_id % int(max(1, int(os.getenv('AURORA_ACK_SCAN_TICKS', '5'))))) == 0:
                ack_tracker.scan_once()
        except Exception:
            pass
        # Optional cancel stub for observability: emits ORDER.CANCEL.REQUEST and ORDER.CANCEL.ACK
        try:
            cancel_stub = os.getenv('AURORA_CANCEL_STUB', 'off').strip().lower() in ('1','true','yes','on')
        except Exception:
            cancel_stub = False
        if cancel_stub and (tick_id % int(os.getenv('AURORA_CANCEL_STUB_EVERY_TICKS', '120')) == 0):
            try:
                cid_c = f"canc-{int(time.time()*1e6)}"
                # Emit cancel request
                try:
                    emitter.emit(
                        "ORDER.CANCEL.REQUEST",
                        {
                            "symbol": ex.symbol.replace('/', ''),
                            "cid": cid_c,
                            "side": (pos_side or ("LONG" if (last_scores[-1] if last_scores else 0.0) >= 0 else "SHORT")),
                            "qty": float(pos_qty or 0.0),
                        },
                        src="runner",
                    )
                except Exception:
                    pass
                # Best-effort cancel on adapter (noop in dry_run)
                try:
                    ex.cancel_all()
                except Exception:
                    pass
                # Emit cancel ack
                try:
                    emitter.emit(
                        "ORDER.CANCEL.ACK",
                        {
                            "symbol": ex.symbol.replace('/', ''),
                            "cid": cid_c,
                            # Unknown oid in stub; real path should include order id
                        },
                        src="runner",
                    )
                except Exception:
                    pass
            except Exception:
                pass
        tick_id += 1
        time.sleep(1.0)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(
        prog="skalp_bot.runner.run_live_aurora",
        description="WiseScalp × Aurora — live scalper runner (testnet-friendly)",
    )
    parser.add_argument(
        "-c",
        "--config",
        dest="config",
        default=None,
    help="Path to YAML config (searches: ./<path>, skalp_bot/configs/<path|name>; if omitted, uses default.aurora.yaml or default.yaml)",
    )
    args = parser.parse_args()
    try:
        main(args.config)
    except KeyboardInterrupt:
        print("\n[WiseScalp x Aurora] interrupted by user — shutting down...")
