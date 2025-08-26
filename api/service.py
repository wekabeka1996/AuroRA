import os
import sys
import yaml
import asyncio
import uvicorn
import json
import time
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse
from pathlib import Path
from pydantic import BaseModel
from prometheus_client import make_asgi_app, Histogram, Gauge, Counter
from dotenv import load_dotenv, find_dotenv

# Ensure project root is on sys.path when running directly (python api/service.py)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ensure environment variables from .env are loaded for all entrypoints (uvicorn or direct)
try:
    load_dotenv(find_dotenv())
except Exception:
    # Non-fatal if dotenv is unavailable; uvicorn --env-file may still be used
    pass

# Lazy import TradingSystem to avoid heavy deps (e.g., torch) at module import time.
# We'll attempt to import it during app lifespan and fall back gracefully if unavailable.
from core.aurora.pretrade import gate_latency, gate_slippage, gate_expected_return, gate_trap
from core.scalper.calibrator import IsotonicCalibrator, CalibInput
from core.scalper.sprt import SPRT, SprtConfig
from core.scalper.trap import TrapWindow
from common.config import load_sprt_cfg
from common.events import EventEmitter
from core.aurora_event_logger import AuroraEventLogger
from core.order_logger import OrderLoggers
from core.ack_tracker import AckTracker
from risk.manager import RiskManager
from aurora.health import HealthGuard
from tools.build_version import build_version_record
from aurora.governance import Governance

# Read version from VERSION file
def get_version():
    try:
        version_file = os.path.join(PROJECT_ROOT, 'VERSION')
        with open(version_file, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception:
        return os.getenv('AURORA_VERSION', 'unknown')


# --- Pydantic models ---
from api.models import (
    PredictionRequest,
    PredictionResponse,
    PretradeCheckRequest,
    PretradeCheckResponse,
)


# --- Initialization ---
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'configs', 'v4_min.yaml')

VERSION = get_version()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup
    try:
        cfg = yaml.safe_load(open(CONFIG_PATH, 'r', encoding='utf-8'))
    except Exception:
        cfg = {}
    # Session log directory
    try:
        sess_dir_env = os.getenv('AURORA_SESSION_DIR')
        if not sess_dir_env:
            stamp = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
            sess_dir = Path('logs') / stamp
            try:
                sess_dir.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            os.environ['AURORA_SESSION_DIR'] = str(sess_dir.resolve())
            app.state.session_dir = sess_dir
        else:
            p = Path(sess_dir_env)
            try:
                p.mkdir(parents=True, exist_ok=True)
            except Exception:
                pass
            app.state.session_dir = p
    except Exception:
        app.state.session_dir = Path('logs')
    # Derived SPRT config
    try:
        sprt_cfg = load_sprt_cfg(cfg)
    except Exception:
        sprt_cfg = None
    app.state.cfg = cfg
    app.state.sprt_cfg = sprt_cfg

    # Event emitter
    try:
        emitter_path = ((cfg or {}).get('logging') or {}).get('path', 'logs/events.jsonl')
    except Exception:
        emitter_path = 'logs/events.jsonl'
    # Canonical path is aurora_events.jsonl; maintain backward compat if configured
    if 'aurora_events' not in emitter_path:
        # default legacy filename was logs/events.jsonl; stick to new canonical file
        emitter_path = 'logs/aurora_events.jsonl'
    # Route events into session directory
    try:
        sess_dir: Path = getattr(app.state, 'session_dir', Path('logs'))
    except Exception:
        sess_dir = Path('logs')
    em_logger = AuroraEventLogger(path=sess_dir / Path(emitter_path).name)
    try:
        print(f"[SESSION] logs dir = {sess_dir}")
    except Exception:
        pass
    try:
        # Attach prometheus counter so emits increment aurora_events_emitted_total{code}
        em_logger.set_counter(EVENTS_EMITTED)
    except Exception:
        pass
    app.state.events_emitter = em_logger

    # AckTracker: background scanner for ORDER.EXPIRE (no-op unless add_submit() is used by producers)
    try:
        try:
            ack_ttl = int(os.getenv('AURORA_ACK_TTL_S', '300'))
        except Exception:
            ack_ttl = 300
        ack_tracker = AckTracker(events_emit=lambda code, d: em_logger.emit(code, d), ttl_s=ack_ttl)
        app.state.ack_tracker = ack_tracker
        import asyncio as _aio
        app.state._ack_scan_stop = _aio.Event()

        async def _ack_scan_loop():
            try:
                period = float(os.getenv('AURORA_ACK_SCAN_PERIOD_S', '1'))
            except Exception:
                period = 1.0
            # Periodically run scan_once until stopped
            while not app.state._ack_scan_stop.is_set():
                try:
                    ack_tracker.scan_once()
                except Exception:
                    pass
                try:
                    await _aio.wait_for(app.state._ack_scan_stop.wait(), timeout=period)
                except _aio.TimeoutError:
                    continue

        # start scan task
        app.state._ack_scan_task = _aio.create_task(_ack_scan_loop())
    except Exception:
        app.state.ack_tracker = None

    # Order loggers (success/failed/denied)
    try:
        # Order logs into session directory
        app.state.order_loggers = OrderLoggers(
            success_path=(getattr(app.state, 'session_dir', Path('logs')) / 'orders_success.jsonl'),
            failed_path=(getattr(app.state, 'session_dir', Path('logs')) / 'orders_failed.jsonl'),
            denied_path=(getattr(app.state, 'session_dir', Path('logs')) / 'orders_denied.jsonl'),
        )
    except Exception:
        app.state.order_loggers = None

    # Trap window
    trap_cfg = (cfg or {}).get('trap') or {}
    try:
        window_s = float(trap_cfg.get('window_s', 2.0))
    except Exception:
        window_s = 2.0
    try:
        levels = int(trap_cfg.get('levels', 5))
    except Exception:
        levels = 5
    app.state.trap_window = TrapWindow(window_s=window_s, levels=levels)

    # Health guard (latency p95)
    try:
        guard_cfg = (cfg or {}).get('aurora', {}) or {}
        l_guard_ms = float(guard_cfg.get('latency_guard_ms', os.getenv('AURORA_LATENCY_GUARD_MS', 30)))
        l_window_sec = int(guard_cfg.get('latency_window_sec', os.getenv('AURORA_LATENCY_WINDOW_SEC', 60)))
        l_cooloff = int(guard_cfg.get('cooloff_base_sec', os.getenv('AURORA_COOLOFF_SEC', 120)))
        l_halt_rep = int(guard_cfg.get('halt_threshold_repeats', os.getenv('AURORA_HALT_THRESHOLD_REPEATS', 2)))
    except Exception:
        l_guard_ms, l_window_sec, l_cooloff, l_halt_rep = 30.0, 60, 120, 2
    app.state.health_guard = HealthGuard(
        threshold_ms=l_guard_ms,
        window_sec=l_window_sec,
        base_cooloff_sec=l_cooloff,
        halt_threshold_repeats=l_halt_rep,
    )

    # Trading system (optional). Import lazily so missing torch doesn't break API for shadow-mode gates.
    try:
        ts = None
        try:
            from importlib import import_module
            mod = import_module('trading.main_loop')
            TradingSystem = getattr(mod, 'TradingSystem', None)
        except Exception:
            TradingSystem = None
        if TradingSystem is not None:
            try:
                ts = TradingSystem(cfg)
            except Exception:
                ts = None
    except Exception:
        ts = None
    app.state.trading_system = ts

    # Risk manager
    try:
        app.state.risk_manager = RiskManager(cfg)
    except Exception:
        app.state.risk_manager = RiskManager({})

        # Governance
        try:
            app.state.governance = Governance(cfg)
        except Exception:
            app.state.governance = Governance({})

    yield

    # shutdown
    emitter = getattr(app.state, 'events_emitter', None)
    if emitter is not None and hasattr(emitter, 'close'):
        try:
            emitter.close()
        except Exception:
            pass
    # Stop ack scanner task
    try:
        stp = getattr(app.state, '_ack_scan_stop', None)
        tsk = getattr(app.state, '_ack_scan_task', None)
        if stp is not None:
            stp.set()
        if tsk is not None:
            try:
                import asyncio as _aio
                await _aio.wait_for(tsk, timeout=1.5)
            except Exception:
                pass
    except Exception:
        pass


app = FastAPI(
    title="AURORA Trading API",
    version=VERSION,
    description="API for the unified certifiable regime-aware trading system.",
    lifespan=lifespan,
)

# Prometheus metrics
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

LATENCY = Histogram('aurora_prediction_latency_ms', 'Prediction latency in milliseconds', buckets=(1, 2, 5, 7.5, 10, 15, 25, 50, 75, 100, 150, 250))
KAPPA_PLUS = Gauge('aurora_kappa_plus', 'Current kappa plus uncertainty metric')
REGIME = Gauge('aurora_regime', 'Current detected market regime')
REQUESTS = Counter('aurora_prediction_requests_total', 'Total prediction requests')
OPS_TOKEN_ROTATIONS = Counter('aurora_ops_token_rotations_total', 'Total OPS token rotations')
EVENTS_EMITTED = Counter('aurora_events_emitted_total', 'Total Aurora events emitted', ['code'])
ORDERS_SUCCESS = Counter('aurora_orders_success_total', 'Total successful orders recorded')
ORDERS_DENIED = Counter('aurora_orders_denied_total', 'Total denied orders recorded')
ORDERS_REJECTED = Counter('aurora_orders_rejected_total', 'Total rejected orders recorded')
OPS_AUTH_FAIL = Counter('aurora_ops_auth_fail_total', 'Total failed OPS auth attempts')


# --- Security middleware for OPS ---
from fastapi import Depends
from fastapi import Header


def _ops_auth(x_ops_token: str | None = Header(default=None, alias="X-OPS-TOKEN")):
    cfg = getattr(app.state, 'cfg', {}) or {}
    sec = (cfg.get('security') or {})
    # runtime token may be rotated and stored in app.state
    token_runtime = getattr(app.state, 'ops_token', None)
    env_token = os.getenv('OPS_TOKEN')
    alias_token = os.getenv('AURORA_OPS_TOKEN')
    token = token_runtime or sec.get('ops_token') or env_token or alias_token
    # Emit WARN if alias is used
    if env_token is None and alias_token is not None:
        try:
            em: AuroraEventLogger | None = getattr(app.state, 'events_emitter', None)
            if em:
                em.emit('OPS.TOKEN.ALIAS_USED', {"alias": "AURORA_OPS_TOKEN"})
        except Exception:
            pass
    allowlist = sec.get('allowlist', ['127.0.0.1', '::1'])
    # Note: IP allowlist can be enforced at reverse-proxy; here we only check token.
    if not token:
        # If no token configured, deny by default (fail-closed)
        OPS_AUTH_FAIL.inc()
        raise HTTPException(status_code=401, detail="OPS token not configured")
    if x_ops_token is None:
        OPS_AUTH_FAIL.inc()
        raise HTTPException(status_code=401, detail="Missing X-OPS-TOKEN")
    if x_ops_token != token:
        OPS_AUTH_FAIL.inc()
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


# --- API Endpoints ---
@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    try:
        ts = getattr(app.state, 'trading_system', None)
        if ts is None:
            raise HTTPException(status_code=503, detail="Trading system not initialized")

        result = await asyncio.wait_for(
            asyncio.to_thread(ts.predict, request.model_dump()),
            timeout=((getattr(app.state, 'cfg', {}) or {}).get('trading', {}) or {}).get('max_latency_ms', 1000) / 1000.0,
        )
        REQUESTS.inc()
        LATENCY.observe(result['latency_ms'])
        REGIME.set(result['regime'])
        return PredictionResponse(
            forecast=result['forecast'],
            interval_lower=result['interval'][0],
            interval_upper=result['interval'][1],
            weights=result['weights'].tolist() if hasattr(result['weights'], 'tolist') else result['weights'],
            kappa_plus=result['kappa_plus'],
            regime=result['regime'],
            latency_ms=result['latency_ms'],
        )
    except asyncio.TimeoutError:
        slo = ((getattr(app.state, 'cfg', {}) or {}).get('trading', {}) or {}).get('max_latency_ms', 1000)
        raise HTTPException(status_code=503, detail=f"Prediction timeout: Service busy or latency SLO ({slo}ms) exceeded.")
    except Exception as e:
        print(f"[ERROR] Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")


@app.get("/version")
async def version():
    return {"version": VERSION}


@app.get("/")
async def root():
    return RedirectResponse(url="/docs", status_code=307)


@app.get("/health")
async def health():
    ts = getattr(app.state, 'trading_system', None)
    model_loaded = ts is not None and ts.student is not None and ts.router is not None
    # Always return 200 for liveness-style health with details; readiness is a separate endpoint
    cfg_all = getattr(app.state, 'cfg', {}) or {}
    order_profile = (cfg_all.get('pretrade', {}) or {}).get('order_profile', 'er_before_slip')
    order_profile = os.getenv('PRETRADE_ORDER_PROFILE', order_profile)
    return {
        "status": "healthy" if model_loaded else "starting",
        "models_loaded": bool(model_loaded),
        "version": build_version_record(order_profile),
    }


@app.get("/liveness")
async def liveness(_: bool = Depends(_ops_auth)):
    """Fast liveness probe: returns 200 if process is up."""
    return {"ok": True}


@app.get("/readiness")
async def readiness(_: bool = Depends(_ops_auth)):
    """Readiness probe: include config and halt state."""
    ts = getattr(app.state, 'trading_system', None)
    model_loaded = ts is not None and ts.student is not None and ts.router is not None
    cfg_loaded = bool(getattr(app.state, 'cfg', {}) or {})
    gov: Governance | None = getattr(app.state, 'governance', None)
    halt = False
    if gov is not None:
        try:
            halt = gov._is_halted()  # internal state is okay for readiness
        except Exception:
            halt = False
    last_event_ts = getattr(app.state, 'last_event_ts', None)
    body = {"config_loaded": cfg_loaded, "last_event_ts": last_event_ts, "halt": halt, "models_loaded": model_loaded}
    if model_loaded:
        return body
    raise HTTPException(status_code=503, detail=body)


@app.post("/pretrade/check", response_model=PretradeCheckResponse)
async def pretrade_check(request: Request, req: PretradeCheckRequest):
    try:
        mode = (req.account or {}).get('mode', os.getenv('AURORA_MODE', 'shadow'))
        max_qty = float((req.order or {}).get('qty', 0.0) or 0.0)
        m = req.market or {}
        latency_ms = float(m.get('latency_ms', 0.0) or 0.0)
        slip_bps_est = float(m.get('slip_bps_est', 0.0) or 0.0)
        a_bps = float(m.get('a_bps', 0.0) or 0.0)
        b_bps = float(m.get('b_bps', 0.0) or 0.0)
        score = float(m.get('score', 0.0) or 0.0)
        regime = str(m.get('mode_regime', 'normal'))
        spread_bps = float(m.get('spread_bps', 0.0) or 0.0)
        sprt_samples = m.get('sprt_samples')
        trap_cancel_deltas = m.get('trap_cancel_deltas')
        trap_add_deltas = m.get('trap_add_deltas')
        trap_trades_cnt = m.get('trap_trades_cnt')
        pnl_today_pct = m.get('pnl_today_pct')
        open_positions = m.get('open_positions')
        base_notional = float((req.order or {}).get('base_notional', (req.order or {}).get('notional', 0.0)) or 0.0)

        try:
            lmax_ms = int(os.getenv('AURORA_LMAX_MS', '30'))
        except Exception:
            lmax_ms = 30

        emitter: EventEmitter | None = getattr(request.app.state, 'events_emitter', None)
        tw: TrapWindow | None = getattr(request.app.state, 'trap_window', None)

        allow = True
        reason = 'ok'
        # If prod mode and trading system is not ready, mark as unhealthy but still allow
        # advisory evaluations of ER/slippage for observability.
        prod_unhealthy = False
        if mode == 'prod':
            ts = getattr(request.app.state, 'trading_system', None)
            if ts is None or ts.student is None or ts.router is None:
                allow, reason = False, 'service_unhealthy'
                prod_unhealthy = True

        reasons: list[str] = []

        # Latency guard immediate threshold
        if allow and not gate_latency(latency_ms=latency_ms, lmax_ms=float(lmax_ms), reasons=reasons):
            allow, reason = False, 'latency_guard'
            if emitter:
                emitter.emit(
                    type="HEALTH.LATENCY_HIGH",
                    severity="warning",
                    code="HEALTH.LATENCY_HIGH",
                    payload={"latency_ms": latency_ms, "lmax_ms": float(lmax_ms)},
                )

        # Record latency and enforce p95-based escalations
        hg: HealthGuard | None = getattr(request.app.state, 'health_guard', None)
        if hg is not None:
            ok, p95 = hg.record(latency_ms)
            if not ok and emitter:
                emitter.emit(
                    type="HEALTH.LATENCY_P95_HIGH",
                    severity="warning",
                    code="HEALTH.LATENCY_P95_HIGH",
                    payload={"p95_ms": p95, "threshold": hg.threshold_ms},
                )
            ok2, reason_h = hg.enforce()
            if allow and not ok2:
                allow = False
                reason = f"latency_{reason_h}"
                reasons.append(reason)
                if emitter:
                    emitter.emit(
                        type="AURORA.ESCALATION",
                        severity="warning",
                        code="AURORA.ESCALATION",
                        payload={"state": hg.snapshot()},
                    )

        # risk_obs/risk_scale placeholders (risk gate runs later)
        rman: RiskManager | None = getattr(request.app.state, 'risk_manager', None)
        risk_obs = None
        risk_scale = 1.0

        # TRAP guard (z-score + score based) with rollback
        trap_obs = None
        if allow and trap_cancel_deltas is not None and trap_add_deltas is not None and trap_trades_cnt is not None:
            try:
                z_threshold = float(os.getenv('AURORA_TRAP_Z_THRESHOLD', '1.64'))
                cancel_pctl = int(os.getenv('AURORA_TRAP_CANCEL_PCTL', '90'))
            except Exception:
                z_threshold, cancel_pctl = 1.64, 90

            obi_sign = m.get('obi_sign')
            tfi_sign = m.get('tfi_sign')

            cancel_d = [float(x) for x in trap_cancel_deltas]
            add_d = [float(x) for x in trap_add_deltas]
            trades_cnt = int(trap_trades_cnt)

            if tw is None:
                try:
                    trap_cfg_local = (getattr(request.app.state, 'cfg', {}) or {}).get('trap', {}) or {}
                    window_s_local = float(trap_cfg_local.get('window_s', 2.0))
                    levels_local = int(trap_cfg_local.get('levels', 5))
                except Exception:
                    window_s_local, levels_local = 2.0, 5
                tw = TrapWindow(window_s=window_s_local, levels=levels_local)
                try:
                    setattr(request.app.state, 'trap_window', tw)
                except Exception:
                    pass

            # TRAP guard enable switch: env overrides YAML guards.trap_guard_enabled
            cfg_all = getattr(request.app.state, 'cfg', {}) or {}
            guards_cfg = (cfg_all.get('guards') or {})
            # Default ON when config is missing (tests clear startup). If YAML explicitly sets false, honor it.
            default_trap_on = bool(guards_cfg.get('trap_guard_enabled', True))
            # In pytest, force default ON for determinism unless TRAP_GUARD explicitly provided
            if os.getenv('PYTEST_CURRENT_TEST'):
                default_trap_on = True
            trap_guard_env = os.getenv('TRAP_GUARD', 'on' if default_trap_on else 'off').lower()

            allow_trap, metrics = gate_trap(
                tw,
                cancel_deltas=cancel_d,
                add_deltas=add_d,
                trades_cnt=trades_cnt,
                z_threshold=z_threshold,
                cancel_pctl=cancel_pctl,
                obi_sign=int(obi_sign) if obi_sign is not None else None,
                tfi_sign=int(tfi_sign) if tfi_sign is not None else None,
                reasons=reasons,
            )

            # Compute trap_score ∈ [0,1]
            try:
                from core.scalper.trap import trap_score_from_features
                cancel_sum = float(sum(max(x, 0.0) for x in cancel_d))
                add_sum = float(sum(max(x, 0.0) for x in add_d))
                denom = max(1e-6, cancel_sum + add_sum)
                cancel_ratio = cancel_sum / denom
                dt_s = getattr(tw, 'window_s', 2.0) or 2.0
                repl_rate = float(add_sum) / float(dt_s) if dt_s > 0 else 0.0
                repl_ms_proxy = 1000.0 if repl_rate <= 0 else max(0.0, 250.0 / repl_rate)
                trap_score = float(trap_score_from_features(cancel_ratio, repl_ms_proxy))
            except Exception:
                trap_score = None

            trap_threshold = float(os.getenv('AURORA_TRAP_THRESHOLD', '0.8'))
            if allow and trap_score is not None and trap_guard_env not in {'off', '0', 'false'}:
                if trap_score > trap_threshold:
                    allow = False
                    reason = 'trap_guard_score'
                    reasons.append(f"trap_guard_score:{trap_score:.2f}>{trap_threshold:.2f}")
                    if emitter:
                        emitter.emit(
                            type="POLICY.TRAP_GUARD",
                            severity="warning",
                            code="POLICY.TRAP_GUARD",
                            payload={"trap_score": trap_score, "threshold": trap_threshold},
                        )

            trap_obs = {
                'trap_z': metrics.trap_z,
                'cancel_rate': metrics.cancel_rate,
                'repl_rate': metrics.repl_rate,
                'n_trades': metrics.n_trades,
                'trap_score': trap_score,
            }

            # (debug removed)

            if not allow_trap and trap_guard_env not in {'off', '0', 'false'}:
                allow, reason = False, 'trap_guard'
                if emitter:
                    emitter.emit(
                        type="POLICY.TRAP_BLOCK",
                        severity="warning",
                        code="POLICY.TRAP_BLOCK",
                        payload={
                            "trap_z": metrics.trap_z,
                            "cancel_rate": metrics.cancel_rate,
                            "repl_rate": metrics.repl_rate,
                            "n_trades": metrics.n_trades,
                        },
                    )

        # SPRT observability placeholders
        sprt_decision = None
        sprt_llr = None
        sprt_n = None

        # Determine order profile: expected return vs slippage
        cfg_all = getattr(request.app.state, 'cfg', {}) or {}
        order_profile = (cfg_all.get('pretrade', {}) or {}).get('order_profile', 'er_before_slip')
        order_profile = os.getenv('PRETRADE_ORDER_PROFILE', order_profile)

        def _run_expected_return():
            nonlocal allow, reason
            # Always evaluate ER for observability (shadow/prod_unhealthy even if earlier guard blocked).
            # Only change the decision (allow) if ER is below threshold AND gate wasn't blocked yet.
            fees_bps_local = float(req.fees_bps or 0.0)
            cal = IsotonicCalibrator()
            ci = CalibInput(score=score, a_bps=a_bps, b_bps=b_bps, fees_bps=fees_bps_local, slip_bps=slip_bps_est, regime=regime)
            out_local = cal.e_pi_bps(ci)
            try:
                pi_min_local = float(os.getenv('AURORA_PI_MIN_BPS', '2.0'))
            except Exception:
                pi_min_local = 2.0
            er_ok = gate_expected_return(e_pi_bps=out_local.e_pi_bps, pi_min_bps=pi_min_local, reasons=reasons)
            if er_ok:
                # Positive ER decision (advisory): record acceptance even if other guards block.
                reasons.append("expected_return_accept")
                if emitter:
                    emitter.emit(
                        type="POLICY.DECISION",
                        severity=None,
                        code="AURORA.EXPECTED_RETURN_ACCEPT",
                        payload={
                            "e_pi_bps": out_local.e_pi_bps,
                            "pi_min_bps": pi_min_local,
                            "fees_bps": fees_bps_local,
                            "slip_bps": slip_bps_est,
                            "score": score,
                            "regime": regime,
                        },
                    )
                # Do not change allow here; other guards may have blocked already.
            else:
                # ER below threshold: emit warning and block only if currently allowed (not already blocked)
                if emitter:
                    emitter.emit(
                        type="AURORA.RISK_WARN",
                        severity="warning",
                        code="AURORA.EXPECTED_RETURN_LOW",
                        payload={"e_pi_bps": out_local.e_pi_bps, "pi_min_bps": pi_min_local},
                    )
                if allow:
                    allow, reason = False, 'expected_return_gate'

        def _run_slippage():
            nonlocal allow, reason
            try:
                eta_local = float(os.getenv('AURORA_SLIP_ETA', '0.3'))
            except Exception:
                eta_local = 0.3
            if allow and not gate_slippage(slip_bps=slip_bps_est, b_bps=b_bps, eta_fraction_of_b=eta_local, reasons=reasons):
                allow, reason = False, 'slippage_guard'
                if emitter:
                    emitter.emit(
                        type="AURORA.RISK_WARN",
                        severity="warning",
                        code="AURORA.SLIPPAGE_GUARD",
                        payload={"slip_bps": slip_bps_est, "b_bps": b_bps, "eta": eta_local},
                    )

        if str(order_profile).lower() == 'slip_before_er':
            _run_slippage()
            _run_expected_return()
        else:
            _run_expected_return()
            _run_slippage()

        # Risk caps (daily DD, max concurrent, size scale) — after expected_return, before SPRT
        if allow and rman is not None:
            try:
                allow_risk, reason_r, scaled_notional, rctx = rman.decide(
                    base_notional=base_notional,
                    pnl_today_pct=float(pnl_today_pct) if pnl_today_pct is not None else None,
                    open_positions=int(open_positions) if open_positions is not None else None,
                )
                risk_obs = {'cfg': rman.snapshot(), 'ctx': rctx}
                risk_scale = float(rctx.get('size_scale', 1.0))
                if not allow_risk:
                    allow, reason = False, reason_r or 'risk_block'
                    reasons.append(reason)
                    if emitter:
                        emitter.emit(
                            type="RISK.DENY",
                            severity="warning",
                            code="RISK.DENY",
                            payload={"reason": reason, "ctx": rctx},
                        )
            except Exception as e:
                reasons.append(f"risk_error:{e}")

        # Optional SPRT reconfirmation
        if allow and sprt_samples is not None:
            sprt_enabled_env = os.getenv('AURORA_SPRT_ENABLED')
            if sprt_enabled_env is None or str(sprt_enabled_env).lower() in {"1", "true", "yes"}:
                try:
                    scfg = getattr(request.app.state, 'sprt_cfg', None)
                    if scfg is not None and getattr(scfg, 'enabled', True):
                        sigma = scfg.sigma
                        A = scfg.A
                        B = scfg.B
                        max_obs = scfg.max_obs
                    else:
                        sigma, A, B, max_obs = 1.0, 2.0, -2.0, 10
                    cfg_s = SprtConfig(mu0=0.0, mu1=score, sigma=sigma, A=A, B=B, max_obs=max_obs)
                    sprt = SPRT(cfg_s)
                    try:
                        timeout_ms = int(os.getenv('AURORA_SPRT_TIMEOUT_MS', '500'))
                    except Exception:
                        timeout_ms = 500
                    sprt_decision = sprt.run_with_timeout([float(x) for x in sprt_samples], time_limit_ms=timeout_ms)
                    sprt_llr = sprt.llr
                    sprt_n = sprt.n_obs
                    if sprt_decision == "REJECT":
                        allow, reason = False, 'sprt_reject'
                        reasons.append("sprt_reject")
                    elif sprt_decision == "ACCEPT":
                        reasons.append("sprt_accept")
                    else:
                        reasons.append("sprt_continue")
                except Exception:
                    reasons.append("sprt_error")

        if spread_bps > 100.0:
            allow, reason = False, f'spread_bps_too_wide:{spread_bps:.1f}'

        obs = {
            'gate_state': 'PASS' if allow else 'BLOCK',
            'spread_bps': spread_bps,
            'mode': mode,
            'latency_ms': latency_ms,
            'slip_bps_est': slip_bps_est,
            'a_bps': a_bps,
            'b_bps': b_bps,
            'score': score,
            'risk': risk_obs,
            'trap': trap_obs,
            'sprt': {
                'decision': sprt_decision,
                'llr': sprt_llr,
                'n_obs': sprt_n,
            },
            'reasons': reasons,
        }

        quotas = {'trades_pm_left': 999, 'symbol_exposure_left_usdt': 1e12}

        # If gate denies, log into denied orders stream
        try:
            if not allow:
                ol: OrderLoggers | None = getattr(request.app.state, 'order_loggers', None)
                if ol is None:
                    # Lazy init to keep counters tied to actual writes even if lifespan didn't run
                    try:
                        ol = OrderLoggers()
                        setattr(request.app.state, 'order_loggers', ol)
                    except Exception:
                        ol = None
                if ol is not None:
                    o = req.order or {}
                    ol.log_denied(
                        ts=int(time.time() * 1000),
                        symbol=o.get('symbol'),
                        side=o.get('side'),
                        qty=o.get('qty'),
                        price=o.get('price'),
                        deny_reason=reason,
                        reasons=reasons,
                        observability=obs,
                    )
                    try:
                        ORDERS_DENIED.inc()
                    except Exception:
                        pass
        except Exception:
            pass

        if emitter:
            emitter.emit(
                type="POLICY.DECISION",
                severity=None,
                code=None,
                payload={
                    "decision": "EXECUTE" if allow else "NO_OP",
                    "reasons": reasons,
                    "mode": mode,
                    "observability": obs,
                },
            )

        return PretradeCheckResponse(allow=allow, max_qty=max_qty, reason=reason, observability=obs, quotas=quotas, risk_scale=risk_scale)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


@app.post("/posttrade/log")
async def posttrade_log(request: Request, payload: dict):
    try:
        # Emit as event for consolidated observability
        emitter: EventEmitter | None = getattr(request.app.state, 'events_emitter', None)
        if emitter:
            try:
                emitter.emit(type="POSTTRADE.LOG", severity=None, code=None, payload=payload)
            except Exception:
                pass

        # Persist raw payload line-by-line into logs/orders.jsonl (path configurable via configs.logging.orders_path)
        try:
            cfg_all = getattr(request.app.state, 'cfg', {}) or {}
            default_orders = (getattr(request.app.state, 'session_dir', Path('logs')) / 'orders.jsonl')
            cfg_orders = ((cfg_all.get('logging') or {}).get('orders_path'))
            # Always place consolidated orders file under session dir, keep only basename
            orders_path = str((getattr(request.app.state, 'session_dir', Path('logs')) / (Path(cfg_orders).name if cfg_orders else default_orders.name)))
        except Exception:
            orders_path = str(getattr(request.app.state, 'session_dir', Path('logs')) / 'orders.jsonl')
        try:
            p = Path(orders_path)
            p.parent.mkdir(parents=True, exist_ok=True)
            rec = dict(payload)
            rec.setdefault('ts_server', int(time.time() * 1000))
            with p.open('a', encoding='utf-8') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        except Exception:
            # do not fail the API if file-write has issues
            pass

        # Also route into per-stream order logs and emit canonical ORDER.* events
        try:
            ol: OrderLoggers | None = getattr(request.app.state, 'order_loggers', None)
            em_ev: AuroraEventLogger | None = getattr(request.app.state, 'events_emitter', None)
            if ol is None:
                # Lazy init to ensure per-stream writes happen in tests without lifespan
                try:
                    ol = OrderLoggers()
                    setattr(request.app.state, 'order_loggers', ol)
                except Exception:
                    ol = None
            if ol is not None:
                rec = dict(payload)
                status = str(rec.get('status', '')).lower()
                is_failed = bool(rec.get('error') or rec.get('error_code') or rec.get('error_msg'))
                is_success = status in {"filled", "partially_filled", "partial", "closed"} or (rec.get('filled') or 0) > 0
                base = {
                    'ts': rec.get('ts') or rec.get('ts_server') or int(time.time() * 1000),
                    'symbol': rec.get('symbol'),
                    'side': rec.get('side'),
                    'qty': rec.get('qty') or rec.get('amount'),
                    'price': rec.get('price'),
                    'order_id': rec.get('order_id') or rec.get('id'),
                    'status': rec.get('status'),
                }
                if is_failed:
                    base.update({'error_code': rec.get('error_code'), 'error_msg': rec.get('error_msg'), 'retry': rec.get('retry')})
                    ol.log_failed(**base)
                    # Emit ORDER.REJECT event
                    try:
                        if em_ev:
                            em_ev.emit(
                                'ORDER.REJECT',
                                {
                                    'symbol': base.get('symbol'),
                                    'oid': base.get('order_id'),
                                    'side': base.get('side'),
                                    'qty': base.get('qty'),
                                    'price': base.get('price'),
                                    'reason_code': base.get('error_code'),
                                    'reason_detail': base.get('error_msg'),
                                },
                                src='api',
                            )
                    except Exception:
                        pass
                    try:
                        ORDERS_REJECTED.inc()
                    except Exception:
                        pass
                elif is_success:
                    base.update({'fill_qty': rec.get('filled'), 'avg_price': rec.get('average') or rec.get('avg_price'), 'fees': rec.get('fee') or rec.get('fees')})
                    ol.log_success(**base)
                    # Emit ORDER.PARTIAL or ORDER.FILL based on filled quantity vs qty if available
                    try:
                        if em_ev:
                            fill_qty = rec.get('filled')
                            qty = rec.get('qty') or rec.get('amount')
                            code = 'ORDER.FILL'
                            try:
                                if fill_qty is not None and qty is not None and float(fill_qty) < float(qty):
                                    code = 'ORDER.PARTIAL'
                            except Exception:
                                code = 'ORDER.FILL'
                            em_ev.emit(
                                code,
                                {
                                    'symbol': base.get('symbol'),
                                    'oid': base.get('order_id'),
                                    'side': base.get('side'),
                                    'qty': qty,
                                    'price': base.get('price') or base.get('avg_price'),
                                    'fill_qty': fill_qty,
                                },
                                src='api',
                            )
                    except Exception:
                        pass
                    try:
                        ORDERS_SUCCESS.inc()
                    except Exception:
                        pass
                else:
                    # if uncertain status, conservatively log as failed
                    ol.log_failed(**base)
                    try:
                        if em_ev:
                            em_ev.emit(
                                'ORDER.REJECT',
                                {
                                    'symbol': base.get('symbol'),
                                    'oid': base.get('order_id'),
                                    'side': base.get('side'),
                                    'qty': base.get('qty'),
                                    'price': base.get('price'),
                                    'reason_detail': 'uncertain_status',
                                },
                                src='api',
                            )
                    except Exception:
                        pass
                    try:
                        ORDERS_REJECTED.inc()
                    except Exception:
                        pass
        except Exception:
            pass

        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))


if __name__ == '__main__':
    host = ((app.state.cfg or {}).get('api', {}) or {}).get('host', '0.0.0.0') if hasattr(app.state, 'cfg') else '0.0.0.0'
    port = ((app.state.cfg or {}).get('api', {}) or {}).get('port', 8000) if hasattr(app.state, 'cfg') else 8000
    uvicorn.run(app, host=host, port=port)

# --- OPS Endpoints ---
@app.post("/ops/cooloff/{sec}")
async def ops_cooloff(sec: int, _: bool = Depends(_ops_auth)):
    hg: HealthGuard | None = getattr(app.state, 'health_guard', None)
    if hg is None:
        raise HTTPException(status_code=503, detail="health_guard not initialized")
    until = hg.cooloff(sec)
    emitter: EventEmitter | None = getattr(app.state, 'events_emitter', None)
    if emitter:
        emitter.emit(type="AURORA.COOL_OFF", severity="info", code="AURORA.COOL_OFF", payload={"until": until})
    return {"status": "ok", "until": until}


@app.post("/ops/reset")
async def ops_reset(_: bool = Depends(_ops_auth)):
    hg: HealthGuard | None = getattr(app.state, 'health_guard', None)
    if hg is None:
        raise HTTPException(status_code=503, detail="health_guard not initialized")
    hg.reset()
    emitter: EventEmitter | None = getattr(app.state, 'events_emitter', None)
    if emitter:
        emitter.emit(type="OPS.RESET", severity="info", code="OPS.RESET", payload={"state": hg.snapshot()})
    return {"status": "ok", "state": hg.snapshot()}


@app.post("/aurora/{mode}")
async def ops_arm_disarm(mode: str, _: bool = Depends(_ops_auth)):
    hg: HealthGuard | None = getattr(app.state, 'health_guard', None)
    if hg is None:
        raise HTTPException(status_code=503, detail="health_guard not initialized")
    if mode.lower() == 'arm':
        hg.arm()
    elif mode.lower() == 'disarm':
        hg.disarm()
    else:
        raise HTTPException(status_code=400, detail="mode must be 'arm' or 'disarm'")
    emitter: EventEmitter | None = getattr(app.state, 'events_emitter', None)
    if emitter:
        emitter.emit(type="AURORA.ARM_STATE", severity="info", code="AURORA.ARM_STATE", payload={"state": hg.snapshot()})
    return {"status": "ok", "state": hg.snapshot()}


# --- Risk OPS Endpoints ---
@app.get("/risk/snapshot")
async def risk_snapshot(_: bool = Depends(_ops_auth)):
    rman: RiskManager | None = getattr(app.state, 'risk_manager', None)
    if rman is None:
        raise HTTPException(status_code=503, detail="risk_manager not initialized")
    return {"status": "ok", "risk": rman.snapshot()}


class RiskSetRequest(BaseModel):
    dd_day_pct: float | None = None
    max_concurrent: int | None = None
    size_scale: float | None = None


@app.post("/risk/set")
async def risk_set(body: RiskSetRequest, _: bool = Depends(_ops_auth)):
    rman: RiskManager | None = getattr(app.state, 'risk_manager', None)
    if rman is None:
        raise HTTPException(status_code=503, detail="risk_manager not initialized")
    # Update fields if provided
    if body.dd_day_pct is not None:
        rman.cfg.dd_day_pct = float(body.dd_day_pct)
    if body.max_concurrent is not None:
        rman.cfg.max_concurrent = int(body.max_concurrent)
    if body.size_scale is not None:
        rman.cfg.size_scale = max(0.0, min(1.0, float(body.size_scale)))
    emitter: EventEmitter | None = getattr(app.state, 'events_emitter', None)
    if emitter:
        emitter.emit(type="RISK.UPDATE", severity="info", code="RISK.UPDATE", payload={"risk": rman.snapshot()})
    return {"status": "ok", "risk": rman.snapshot()}


class RotateTokenRequest(BaseModel):
    new_token: str


@app.post("/ops/rotate_token")
async def ops_rotate_token(body: RotateTokenRequest, _: bool = Depends(_ops_auth)):
    # accept alias 'new' for convenience
    new_t = (getattr(body, 'new_token', None) or '').strip()
    if not new_t and hasattr(body, 'new'):
        try:
            new_t = str(getattr(body, 'new')).strip()
        except Exception:
            new_t = ''
    if not new_t:
        raise HTTPException(status_code=400, detail="new_token must be non-empty")
    if len(new_t) < 24:
        raise HTTPException(status_code=400, detail="new_token too short (min 24)")
    # simple cooldown: block rotations within 30s window
    import time
    last_rot = getattr(app.state, 'last_token_rotate_ts', 0.0)
    now_ts = time.time()
    if now_ts - last_rot < 30.0:
        raise HTTPException(status_code=429, detail="rotation cooldown active")
    setattr(app.state, 'ops_token', new_t)
    setattr(app.state, 'last_token_rotate_ts', now_ts)
    OPS_TOKEN_ROTATIONS.inc()
    emitter: EventEmitter | None = getattr(app.state, 'events_emitter', None)
    if emitter:
        # mask token in logs, show last 4
        mask = ('****' + new_t[-4:]) if len(new_t) >= 4 else '****'
        emitter.emit(type="OPS.TOKEN_ROTATE", severity="info", code="OPS.TOKEN_ROTATE", payload={"ts": VERSION, "token_mask": mask})
    return {"status": "ok"}
