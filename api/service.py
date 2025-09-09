import os
import sys
import yaml
import asyncio
import uvicorn
import json
import time
import shutil
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse, JSONResponse
from pathlib import Path
from pydantic import BaseModel
from typing import Any, Dict, cast
from prometheus_client import make_asgi_app, Histogram, Gauge, Counter, CollectorRegistry
from dotenv import load_dotenv, find_dotenv
from fastapi.middleware.cors import CORSMiddleware

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
from core.aurora.pipeline import PretradePipeline
from common.config import load_sprt_cfg, load_config_any, load_config_precedence, apply_env_overrides
from common.events import EventEmitter
from core.aurora_event_logger import AuroraEventLogger
from core.order_logger import OrderLoggers
from core.ack_tracker import AckTracker
from risk.manager import RiskManager
from aurora.health import HealthGuard
from tools.build_version import build_version_record
from aurora.governance import Governance
from observability.codes import (
    POLICY_DECISION, AURORA_RISK_WARN, AURORA_EXPECTED_RETURN_ACCEPT,
    AURORA_EXPECTED_RETURN_LOW, AURORA_SLIPPAGE_GUARD, POSTTRADE_LOG
)

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
# Deprecated fallback kept for BC if precedence chain yields empty
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'configs', 'v4_min.yaml')

VERSION = get_version()


@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup - Use new production configuration system
    try:
        from core.config.api_integration import production_lifespan
        async with production_lifespan(app):
            yield
        return
    except ImportError:
        # Fallback to legacy system if new system isn't available
        pass
    
    # Legacy startup for backward compatibility
    # Security bootstrap: require AURORA_API_TOKEN
    api_token = os.getenv('AURORA_API_TOKEN')
    if not api_token or len(api_token.strip()) < 16:
        # Fail startup fast if token is not configured
        raise RuntimeError("AURORA_API_TOKEN is required and must be >=16 chars")

    # Load YAML-first config with env overrides. Precedence:
    # AURORA_CONFIG (path or name) → AURORA_CONFIG_NAME → default CONFIG_PATH
    cfg: dict = {}
    try:
        # Unified precedence: env → defaults chain; then apply env overrides
        cfg = load_config_precedence()
        if not cfg:
            # final fallback for legacy deployments
            cfg = yaml.safe_load(open(CONFIG_PATH, 'r', encoding='utf-8')) or {}
        cfg = apply_env_overrides(cfg)
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
    # Persist overlay path from config for control-plane endpoints
    try:
        ov_path = ((cfg or {}).get('overlays') or {}).get('active', 'profiles/overlays/_active_shadow.yaml')
    except Exception:
        ov_path = 'profiles/overlays/_active_shadow.yaml'
    try:
        p = Path(ov_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        app.state.overlay_path = p
    except Exception:
        app.state.overlay_path = Path('profiles/overlays/_active_shadow.yaml')

    # Validate Aurora runtime mode and environment compatibility  
    from core.env_config import validate_aurora_mode, get_runtime_mode
    
    try:
        aurora_mode, binance_env = get_runtime_mode()
        if isinstance(aurora_mode, str) and aurora_mode.lower() == 'shadow':
            raise RuntimeError("'shadow' runtime mode is removed; use AURORA_MODE=live or testnet")
        
        # Log the runtime configuration
        app.state.aurora_mode = aurora_mode
        app.state.binance_env = binance_env
        
    except Exception as e:
        raise RuntimeError(f"Invalid Aurora runtime configuration: {e}")

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
    # Emit config switched for observability
    try:
        cfg_name = os.getenv('AURORA_CONFIG') or os.getenv('AURORA_CONFIG_NAME') or 'default(v4_min.yaml)'
        em_logger.emit('CONFIG.SWITCHED', {'name': cfg_name})
    except Exception:
        pass

    # AckTracker: background scanner for ORDER.EXPIRE (no-op unless add_submit() is used by producers)
    try:
        try:
            # Prefer cfg.observability.ack.ttl_s, then env alias, then default
            ack_cfg = ((cfg or {}).get('observability') or {}).get('ack') or {}
            ack_ttl = ack_cfg.get('ttl_s')
            if ack_ttl is None:
                ack_ttl = int(os.getenv('AURORA_ACK_TTL_S', '300'))
            ack_ttl = int(ack_ttl)
        except Exception:
            ack_ttl = 300
        ack_tracker = AckTracker(events_emit=lambda code, d: em_logger.emit(code, d), ttl_s=ack_ttl)
        app.state.ack_tracker = ack_tracker
        import asyncio as _aio
        app.state._ack_scan_stop = _aio.Event()

        async def _ack_scan_loop():
            try:
                # Prefer cfg.observability.ack.scan_period_s, then env alias, then default
                ack_cfg2 = ((cfg or {}).get('observability') or {}).get('ack') or {}
                period = ack_cfg2.get('scan_period_s')
                if period is None:
                    period = float(os.getenv('AURORA_ACK_SCAN_PERIOD_S', '1'))
                period = float(period)
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

    # Anti-churn state: per-symbol open rate-limit and cooldown after close (always initialize)
    try:
        aurora_cfg = (cfg or {}).get('aurora', {}) or {}
        min_open_interval_ms = aurora_cfg.get('min_open_interval_ms')
        if min_open_interval_ms is None:
            try:
                min_open_interval_ms = int(os.getenv('AURORA_MIN_OPEN_INTERVAL_MS', '0'))
            except Exception:
                min_open_interval_ms = 0
        else:
            try:
                min_open_interval_ms = int(min_open_interval_ms)
            except Exception:
                min_open_interval_ms = 0
        cooldown_after_close_ms = aurora_cfg.get('cooldown_after_close_ms')
        if cooldown_after_close_ms is None:
            try:
                cooldown_after_close_ms = int(os.getenv('AURORA_COOLDOWN_AFTER_CLOSE_MS', '0'))
            except Exception:
                cooldown_after_close_ms = 0
        else:
            try:
                cooldown_after_close_ms = int(cooldown_after_close_ms)
            except Exception:
                cooldown_after_close_ms = 0
        app.state.min_open_interval_ms = int(max(0, min_open_interval_ms))
        app.state.cooldown_after_close_ms = int(max(0, cooldown_after_close_ms))
        # runtime maps
        app.state._last_open_allow_ms = {}
        app.state._cooldown_until_ms = {}
        # Position state: track open direction and since_ms per symbol
        try:
            mph = aurora_cfg.get('min_position_hold_ms')
            if mph is None:
                mph = int(os.getenv('AURORA_MIN_POSITION_HOLD_MS', '0'))
            else:
                mph = int(mph)
        except Exception:
            mph = 0
        app.state.min_position_hold_ms = int(max(0, mph))
        app.state._position_state = {}
    except Exception:
        app.state.min_open_interval_ms = 0
        app.state.cooldown_after_close_ms = 0
        app.state._last_open_allow_ms = {}
        app.state._cooldown_until_ms = {}
        app.state.min_position_hold_ms = 0
        app.state._position_state = {}

    # Start SLI update loop
    try:
        app.state._sli_task = asyncio.create_task(_sli_update_loop(app))
    except Exception:
        pass

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

    # Stop SLI task
    try:
        t = getattr(app.state, '_sli_task', None)
        if t:
            t.cancel()
    except Exception:
        pass


app = FastAPI(
    title="AURORA Trading API",
    version=VERSION,
    description="API for the unified certifiable regime-aware trading system.",
    lifespan=lifespan,
)

"""
Prometheus metrics: use a dedicated CollectorRegistry per module import to avoid
duplicated timeseries when tests reload this module (importlib.reload).
"""
METRICS_REGISTRY = CollectorRegistry()
metrics_app = make_asgi_app(METRICS_REGISTRY)
app.mount("/metrics", metrics_app)

LATENCY = Histogram('aurora_prediction_latency_ms', 'Prediction latency in milliseconds', buckets=(1, 2, 5, 7.5, 10, 15, 25, 50, 75, 100, 150, 250), registry=METRICS_REGISTRY)
KAPPA_PLUS = Gauge('aurora_kappa_plus', 'Current kappa plus uncertainty metric', registry=METRICS_REGISTRY)
REGIME = Gauge('aurora_regime', 'Current detected market regime', registry=METRICS_REGISTRY)
REQUESTS = Counter('aurora_prediction_requests_total', 'Total prediction requests', registry=METRICS_REGISTRY)
OPS_TOKEN_ROTATIONS = Counter('aurora_ops_token_rotations_total', 'Total OPS token rotations', registry=METRICS_REGISTRY)
EVENTS_EMITTED = Counter('aurora_events_emitted_total', 'Total Aurora events emitted', ['code'], registry=METRICS_REGISTRY)
ORDERS_SUCCESS = Counter('aurora_orders_success_total', 'Total successful orders recorded', registry=METRICS_REGISTRY)
ORDERS_DENIED = Counter('aurora_orders_denied_total', 'Total denied orders recorded', registry=METRICS_REGISTRY)
ORDERS_REJECTED = Counter('aurora_orders_rejected_total', 'Total rejected orders recorded', registry=METRICS_REGISTRY)
OPS_AUTH_FAIL = Counter('aurora_ops_auth_fail_total', 'Total failed OPS auth attempts', registry=METRICS_REGISTRY)

# --- Additional SLI/Business metrics ---
DENY_RATE_15M = Gauge('aurora_deny_rate_15m', 'Deny rate over 15 minutes window', registry=METRICS_REGISTRY)
LATENCY_P99_MS = Gauge('aurora_latency_p99_ms', 'p99 latency in ms over recent window', registry=METRICS_REGISTRY)
ECE_GAUGE = Gauge('aurora_ece', 'Expected Calibration Error', registry=METRICS_REGISTRY)
CVAR95_MIN = Gauge('aurora_cvar95_min', 'CVaR 95% min over recent window', registry=METRICS_REGISTRY)
SSE_CLIENTS = Gauge('aurora_sse_clients', 'Current number of SSE clients', registry=METRICS_REGISTRY)
SSE_DISCONNECTS = Counter('aurora_sse_disconnects_total', 'Total SSE client disconnects', registry=METRICS_REGISTRY)

PARENT_GATE_ALLOW = Counter('aurora_parent_gate_allow_total', 'Parent gate allows', registry=METRICS_REGISTRY)
PARENT_GATE_DENY = Counter('aurora_parent_gate_deny_total', 'Parent gate denies', registry=METRICS_REGISTRY)
EXPECTED_NET_REWARD_BLOCKED = Counter('aurora_expected_net_reward_blocked_total', 'Expected net reward blocks', registry=METRICS_REGISTRY)
ORDERS_SUBMITTED_SHADOW = Counter('aurora_orders_submitted_shadow_total', 'Shadow orders submitted total', registry=METRICS_REGISTRY)

# Model neutral streak per symbol (1 if last 200 p_cal values == 0.5)
MODEL_NEUTRAL_STREAK = Gauge('aurora_model_neutral_streak', 'Neutral p_cal streak', ['symbol'], registry=METRICS_REGISTRY)


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
    token_cfg = sec.get('ops_token')
    # Accept any configured token source to be robust during rotations/tests
    candidates = [t for t in [token_runtime, token_cfg, env_token, alias_token] if t]
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
    if not candidates:
        # If no token configured, deny by default (fail-closed)
        OPS_AUTH_FAIL.inc()
        raise HTTPException(status_code=401, detail="OPS token not configured")
    if x_ops_token is None:
        OPS_AUTH_FAIL.inc()
        raise HTTPException(status_code=401, detail="Missing X-OPS-TOKEN")
    if x_ops_token not in candidates:
        OPS_AUTH_FAIL.inc()
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


def _xauth(x_auth: str | None = Header(default=None, alias="X-Auth-Token")):
    token = os.getenv('AURORA_API_TOKEN')
    if not token:
        raise HTTPException(status_code=503, detail="AURORA_API_TOKEN not configured")
    if x_auth is None:
        raise HTTPException(status_code=401, detail="Missing X-Auth-Token")
    if x_auth != token:
        raise HTTPException(status_code=403, detail="Forbidden")
    return True


# --- X-Auth & IP allowlist & Rate-limit Middleware ---
from starlette.types import ASGIApp, Receive, Scope, Send
from starlette.responses import JSONResponse


def _parse_allowlist_env() -> set[str]:
    v = os.getenv('AURORA_IP_ALLOWLIST', '').strip()
    if not v:
        # Default allow localhost to avoid self-lockout in dev
        return {"127.0.0.1", "::1"}
    return {ip.strip() for ip in v.split(',') if ip.strip()}


def _is_mutating(method: str, path: str) -> bool:
    if method.upper() in {"POST", "PUT", "PATCH", "DELETE"}:
        # exclude known read-only posts if any arise; keep conservative
        return True
    return False


class RateLimiter:
    def __init__(self, rps_general: float = 60.0, rps_mutating: float = 10.0):
        self.rps_g = float(rps_general)
        self.rps_m = float(rps_mutating)
        self.state: dict[str, dict[str, float]] = {}

    def allow(self, ip: str, mutating: bool, now: float | None = None) -> bool:
        now = now or time.time()
        rec = self.state.setdefault(ip, {"tokens_g": self.rps_g, "tokens_m": self.rps_m, "ts": now})
        dt = max(0.0, now - rec["ts"])
        # leak tokens to max capacity
        rec["tokens_g"] = min(self.rps_g, rec["tokens_g"] + dt * self.rps_g)
        rec["tokens_m"] = min(self.rps_m, rec["tokens_m"] + dt * self.rps_m)
        rec["ts"] = now
        if mutating:
            if rec["tokens_m"] >= 1.0 and rec["tokens_g"] >= 1.0:
                rec["tokens_m"] -= 1.0
                rec["tokens_g"] -= 1.0
                return True
            return False
        else:
            if rec["tokens_g"] >= 1.0:
                rec["tokens_g"] -= 1.0
                return True
            return False


_rate_limiter = RateLimiter()
_ip_allow = _parse_allowlist_env()


@app.middleware("http")
async def security_and_rl_middleware(request: Request, call_next):
    # CORS handled by ASGI middleware below; here we do IP + Auth + RL
    # Detect client IP with fallbacks suitable for TestClient
    client_ip = (request.headers.get('x-forwarded-for') or '').split(',')[0].strip()
    if not client_ip:
        client_ip = (request.client.host if request.client else None) or ""
    if client_ip in {"", "testclient"}:
        client_ip = "127.0.0.1"
    if client_ip not in _ip_allow:
        return JSONResponse({"detail": "IP not allowed"}, status_code=403)

    method = request.method
    path = request.url.path
    mutating = _is_mutating(method, path)

    # Require X-Auth-Token for mutating endpoints, except trusted internal control/data paths
    # - /ops/* endpoints are protected by X-OPS-TOKEN dependency (_ops_auth)
    # - /pretrade/* and /posttrade/* are internal data pipes used by runner/tests
    if mutating:
        if not (path.startswith('/ops') or path.startswith('/pretrade') or path.startswith('/posttrade')):
            x_auth = request.headers.get('X-Auth-Token')
            token = os.getenv('AURORA_API_TOKEN')
            if not x_auth:
                return JSONResponse({"detail": "Missing X-Auth-Token"}, status_code=401)
            if not token or x_auth != token:
                return JSONResponse({"detail": "Forbidden"}, status_code=403)

    # Rate limit
    if not _rate_limiter.allow(client_ip, mutating):
        return JSONResponse({"detail": "Too Many Requests"}, status_code=429)

    return await call_next(request)


# Optional CORS (disabled by default; enable via AURORA_CORS_ORIGIN)
cors_origin = os.getenv('AURORA_CORS_ORIGIN', '').strip()
if cors_origin:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[cors_origin],
        allow_credentials=True,
        allow_methods=["GET", "POST", "OPTIONS"],
        allow_headers=["*"],
    )


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
    """Readiness probe: fixed JSON shape and no-store caching."""
    ts = getattr(app.state, 'trading_system', None)
    model_loaded = bool(ts is not None and getattr(ts, 'student', None) is not None and getattr(ts, 'router', None) is not None)
    cfg_loaded = bool(getattr(app.state, 'cfg', {}) or {})
    gov: Governance | None = getattr(app.state, 'governance', None)
    halt = False
    if gov is not None:
        try:
            halt = bool(gov._is_halted())  # internal is acceptable for readiness
        except Exception:
            halt = False
    last_event_ts = getattr(app.state, 'last_event_ts', None)
    body = {"config_loaded": cfg_loaded, "last_event_ts": last_event_ts, "halt": halt, "models_loaded": model_loaded}
    # Always return a dict with fixed shape.
    # When not ready, raise HTTPException with detail=body to align with tests expecting `detail` wrapper.
    if not model_loaded:
        raise HTTPException(status_code=503, detail=body, headers={"Cache-Control": "no-store"})
    return JSONResponse(content=body, status_code=200, headers={"Cache-Control": "no-store"})


@app.post("/pretrade/check", response_model=PretradeCheckResponse)
async def pretrade_check(request: Request, req: PretradeCheckRequest):
    try:
        # Уніфікувати представлення у dict, навіть якщо це Pydantic-моделі
        def _as_dict(v: Any) -> Dict[str, Any]:
            try:
                return cast(Dict[str, Any], v.model_dump())  # type: ignore[attr-defined]
            except Exception:
                try:
                    return dict(v)  # type: ignore[arg-type]
                except Exception:
                    return cast(Dict[str, Any], v or {})

        acc: Dict[str, Any] = _as_dict(req.account)
        o: Dict[str, Any] = _as_dict(req.order)
        m: Dict[str, Any] = _as_dict(req.market)
    except Exception as e:
        # Невалідний формат запиту
        raise HTTPException(status_code=422, detail=str(e))

    mode = (acc or {}).get('mode', os.getenv('AURORA_MODE', 'live'))
    max_qty = float((o or {}).get('qty', 0.0) or 0.0)

    emitter: EventEmitter | None = getattr(request.app.state, 'events_emitter', None)
    # Advisory: if prod and trading system isn't ready, emit a service_unhealthy note
    diagnostics_local: list[str] = []
    if mode == 'prod':
        ts = getattr(request.app.state, 'trading_system', None)
        if ts is None or ts.student is None or ts.router is None:
            diagnostics_local.append('service_unhealthy')
            if emitter:
                try:
                    emitter.emit(
                        type="HEALTH.SERVICE_UNHEALTHY",
                        severity="warning",
                        code="HEALTH.SERVICE_UNHEALTHY",
                        payload={"mode": mode},
                    )
                except Exception:
                    pass

    # Anti-churn precheck (rate-limit opens and respect cooldown after close)
    allow: bool = False
    reason: str = "uninitialized"
    obs: Dict[str, Any]
    risk_scale: float = 1.0
    obs = {"reasons": []}
    pipeline = None
    def _canon_symbol(s: Any) -> str | None:
        try:
            if not s:
                return None
            s2 = str(s).upper().strip()
            # Normalize forms like 'BINANCE:BTC/USDT' -> 'BTC/USDT'
            if ':' in s2:
                s2 = s2.split(':', 1)[-1]
            return s2
        except Exception:
            return None

    try:
        sym_raw = (o or {}).get('symbol') or (m or {}).get('symbol')
        sym = _canon_symbol(sym_raw)
        side = str((o or {}).get('side') or '').lower() or None
        now_ms = int(time.time() * 1000)
        # Per-symbol cooldown after close
        cd_until = getattr(request.app.state, '_cooldown_until_ms', {}).get(sym) if sym else None
        if sym and isinstance(cd_until, (int, float)) and now_ms < int(cd_until) and int(getattr(request.app.state, 'cooldown_after_close_ms', 0)) > 0:
            allow = False
            reason = 'cooldown_after_close_active'
            try:
                remaining = int(cd_until) - now_ms
                obs['cooldown_remaining_ms'] = max(0, remaining)
            except Exception:
                pass
            obs['reasons'].append('cooldown_after_close_active')
            # Emit observability event
            try:
                if emitter:
                    emitter.emit('COOLDOWN.ACTIVE', {'symbol': sym, 'ms_left': obs.get('cooldown_remaining_ms', 0)})
            except Exception:
                pass
        else:
            # Per-symbol minimal interval between open approvals
            min_iv = int(getattr(request.app.state, 'min_open_interval_ms', 0))
            last_ok = getattr(request.app.state, '_last_open_allow_ms', {}).get(sym) if sym else None
            if sym and min_iv > 0 and isinstance(last_ok, (int, float)) and (now_ms - int(last_ok)) < min_iv:
                allow = False
                reason = 'open_rate_limit'
                try:
                    obs['rate_limit_ms_left'] = max(0, min_iv - (now_ms - int(last_ok)))
                except Exception:
                    pass
                obs['reasons'].append('open_rate_limit')
                try:
                    if emitter:
                        emitter.emit('OPEN.RATE_LIMIT', {'symbol': sym, 'ms_left': obs.get('rate_limit_ms_left', 0)})
                except Exception:
                    pass
            else:
                # Enforce min position hold and opposite-side block if a position is open
                pos_state = getattr(request.app.state, '_position_state', {})
                min_hold = int(getattr(request.app.state, 'min_position_hold_ms', 0))
                ps = pos_state.get(sym) if sym else None
                if sym and ps and isinstance(ps, dict):
                    open_side = ps.get('side')
                    since_ms = int(ps.get('since_ms') or 0)
                    if open_side in {'buy','sell'}:
                        # Block opposite side while position alive
                        if side and ((open_side == 'buy' and side == 'sell') or (open_side == 'sell' and side == 'buy')):
                            # Respect min hold window for any side change
                            if min_hold > 0 and now_ms - since_ms < min_hold:
                                allow = False
                                reason = 'position_min_hold_active'
                                obs['reasons'].append('position_min_hold_active')
                                obs['position'] = {'symbol': sym, 'side': open_side, 'age_ms': now_ms - since_ms, 'min_hold_ms': min_hold}
                                try:
                                    if emitter:
                                        emitter.emit('POSITION.MIN_HOLD', {'symbol': sym, 'ms_left': max(0, min_hold - (now_ms - since_ms))})
                                except Exception:
                                    pass
                            else:
                                # Even if hold window elapsed, prevent cross in same tick to avoid self-trade churn
                                allow = False
                                reason = 'opposite_side_block'
                                obs['reasons'].append('opposite_side_block')
                                obs['position'] = {'symbol': sym, 'side': open_side, 'age_ms': now_ms - since_ms}
                                try:
                                    if emitter:
                                        emitter.emit('POSITION.OPPOSITE_BLOCK', {'symbol': sym, 'open_side': open_side})
                                except Exception:
                                    pass
                short_circuit = False
                try:
                    if reason in ('position_min_hold_active','opposite_side_block','open_rate_limit'):
                        short_circuit = True
                except Exception:
                    short_circuit = False
                if not short_circuit:
                    # Run core pipeline when anti-churn didn't block
                    pipeline = PretradePipeline(
                        emitter=emitter,
                        trap_window=getattr(request.app.state, 'trap_window', None),
                        health_guard=getattr(request.app.state, 'health_guard', None),
                        risk_manager=getattr(request.app.state, 'risk_manager', None),
                        governance=getattr(request.app.state, 'governance', None),
                        cfg=getattr(request.app.state, 'cfg', {}) or {},
                    )
                    allow, reason, obs, risk_scale = pipeline.decide(
                        account=acc,
                        order=o,
                        market=m,
                        fees_bps=float(req.fees_bps or 0.0),
                    )
                    # On allow, stamp last allow time for symbol
                    if allow and sym:
                        try:
                            getattr(request.app.state, '_last_open_allow_ms')[sym] = now_ms  # type: ignore[index]
                        except Exception:
                            pass
    except Exception:
        # On error, fallback to running pipeline to avoid false blocks
        pipeline = PretradePipeline(
            emitter=emitter,
            trap_window=getattr(request.app.state, 'trap_window', None),
            health_guard=getattr(request.app.state, 'health_guard', None),
            risk_manager=getattr(request.app.state, 'risk_manager', None),
            governance=getattr(request.app.state, 'governance', None),
            cfg=getattr(request.app.state, 'cfg', {}) or {},
        )
        allow, reason, obs, risk_scale = pipeline.decide(
            account=acc,
            order=o,
            market=m,
            fees_bps=float(req.fees_bps or 0.0),
        )
    # If pipeline created a trap_window lazily, persist it back to app.state
    try:
        if pipeline is not None and getattr(pipeline, 'tw', None) is not None and getattr(request.app.state, 'trap_window', None) is None:
            setattr(request.app.state, 'trap_window', pipeline.tw)
    except Exception:
        pass

    # If blocked due to spread — emit observability event (pipeline computes the decision; we add emit here)
    try:
        if not allow and isinstance(reason, str) and reason.startswith('spread_bps_too_wide') and emitter is not None:
            # extract numbers for payload when possible
            spread_bps_val = obs.get('spread_bps') if isinstance(obs, dict) else None
            cfg_all_s = getattr(request.app.state, 'cfg', {}) or {}
            spread_limit_bps = float(((cfg_all_s.get('guards') or {}).get('spread_bps_limit', 100.0)))
            emitter.emit(
                type="SPREAD_GUARD_TRIP",
                severity="warning",
                code="SPREAD_GUARD_TRIP",
                payload={'spread_bps': float(spread_bps_val or 0.0), 'limit_bps': float(spread_limit_bps)},
            )
    except Exception:
        pass

    # Merge advisory diagnostics (do not contaminate blocking reasons)
    try:
        if diagnostics_local:
            obs.setdefault('diagnostics', [])
            # ensure uniqueness while preserving order
            existing = set(obs['diagnostics']) if isinstance(obs.get('diagnostics'), list) else set()
            for x in diagnostics_local:
                if x not in existing:
                    obs['diagnostics'].append(x)
                    existing.add(x)
    except Exception:
        pass

    quotas = {'trades_pm_left': 999, 'symbol_exposure_left_usdt': 1e12}
    reasons_list = (obs.get('reasons') if isinstance(obs, dict) else None) or []

    # If gate denies, log into denied orders stream
    try:
        if not allow:
            # Increment counter regardless of file writer availability
            try:
                ORDERS_DENIED.inc()
            except Exception:
                pass
            ol: OrderLoggers | None = getattr(request.app.state, 'order_loggers', None)
            if ol is None:
                # Lazy init to keep counters tied to actual writes even if lifespan didn't run
                try:
                    ol = OrderLoggers()
                    setattr(request.app.state, 'order_loggers', ol)
                except Exception:
                    ol = None
            if ol is not None:
                ol.log_denied(
                    ts=int(time.time() * 1000),
                    symbol=o.get('symbol'),
                    side=o.get('side'),
                    qty=o.get('qty'),
                    price=o.get('price'),
                    deny_reason=reason,
                    reasons=reasons_list,
                    observability=obs,
                )
                # Optionally also build a structured OrderDenied schema (best-effort, no-op on failure)
                try:
                    from core.converters import api_order_to_denied_schema
                    _ = api_order_to_denied_schema(
                        decision_id=str(obs.get('decision_id') or ''),
                        order=o,
                        deny_reason=reason,
                        reasons=reasons_list,
                        observability=obs,
                    )
                except Exception:
                    pass
    except Exception:
        pass

    if emitter:
        emitter.emit(
            type=POLICY_DECISION,
            severity=None,
            code=None,
            payload={
                "decision": "EXECUTE" if allow else "NO_OP",
                "reasons": (obs.get('reasons') if isinstance(obs, dict) else None) or [],
                "mode": mode,
                "observability": obs,
            },
        )

    # Update policy counters
    try:
        if allow:
            try:
                PARENT_GATE_ALLOW.inc()
            except Exception:
                pass
        else:
            try:
                PARENT_GATE_DENY.inc()
            except Exception:
                pass
            # If expected net reward is the reason
            rs = (obs.get('reasons') if isinstance(obs, dict) else []) or []
            if any(isinstance(r, str) and 'expected' in r and 'reward' in r and ('low' in r or 'negative' in r) for r in rs):
                try:
                    EXPECTED_NET_REWARD_BLOCKED.inc()
                except Exception:
                    pass
    except Exception:
        pass

    return PretradeCheckResponse(allow=allow, max_qty=max_qty, reason=reason, observability=obs, quotas=quotas, risk_scale=risk_scale)


@app.post("/posttrade/log")
async def posttrade_log(request: Request, payload: dict):
    try:
        # Emit as event for consolidated observability
        emitter: EventEmitter | None = getattr(request.app.state, 'events_emitter', None)
        if emitter:
            try:
                emitter.emit(type=POSTTRADE_LOG, severity=None, code=None, payload=payload)
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
                # If the runner posted the raw CCXT order object under 'response', enrich top-level keys
                try:
                    resp = rec.get('response') or {}
                    if isinstance(resp, dict):
                        # CCXT unified fields are at top-level of resp; exchange raw under resp['info']
                        rec.setdefault('status', resp.get('status') or (resp.get('info') or {}).get('status'))
                        rec.setdefault('filled', resp.get('filled') or (resp.get('info') or {}).get('executedQty'))
                        rec.setdefault('average', resp.get('average') or resp.get('avg_price'))
                        rec.setdefault('id', resp.get('id') or (resp.get('info') or {}).get('orderId'))
                except Exception:
                    pass
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
                    # Optional: build structured core OrderFailed schema (best-effort)
                    try:
                        from core.converters import posttrade_to_failed_schema
                        _ = posttrade_to_failed_schema(rec, decision_id=str(rec.get('decision_id') or ''), snapshot=None)
                    except Exception:
                        pass
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
                    # Update position state on successful orders
                    try:
                        sym_raw = rec.get('symbol')
                        sym = (str(sym_raw).upper().strip() if sym_raw else None)
                        if sym and ':' in sym:
                            sym = sym.split(':', 1)[-1]
                        side = (str(rec.get('side') or '') or '').lower() or None
                        # Determine if this is a close/reduce.
                        action = (str(payload.get('action')).lower() if isinstance(payload, dict) and payload.get('action') is not None else None)
                        close_flag = False
                        try:
                            close_flag = bool((payload.get('close') if isinstance(payload, dict) else False) or (payload.get('reduceOnly') if isinstance(payload, dict) else False))
                            resp2 = payload.get('response') if isinstance(payload, dict) else None
                            if isinstance(resp2, dict):
                                close_flag = close_flag or bool(resp2.get('close') or resp2.get('reduceOnly'))
                        except Exception:
                            close_flag = False
                        ps_map = getattr(request.app.state, '_position_state', None)
                        if isinstance(ps_map, dict) and sym:
                            if action == 'close' or close_flag:
                                # Clear position state on close
                                try:
                                    if sym in ps_map:
                                        ps_map.pop(sym, None)
                                except Exception:
                                    pass
                            else:
                                # Set/refresh position state on open/partial fills
                                try:
                                    ps_map[sym] = {'side': side, 'since_ms': int(base.get('ts') or time.time() * 1000)}
                                except Exception:
                                    pass
                    except Exception:
                        pass
                    # Optional: build structured core OrderSuccess schema (best-effort)
                    try:
                        from core.converters import posttrade_to_success_schema
                        _ = posttrade_to_success_schema(rec, decision_id=str(rec.get('decision_id') or ''), snapshot=None)
                    except Exception:
                        pass
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
                    # Pending/unknown status: write only to consolidated orders.jsonl (above) and do not emit reject.
                    # We'll rely on subsequent updates (fills/partials) to log success, or explicit error fields to log failure.
                    pass
        except Exception:
            pass

        # Anti-churn: when a close/reduce observed, set cooldown for the symbol
        try:
            def _canon_symbol(s: Any) -> str | None:
                try:
                    if not s:
                        return None
                    s2 = str(s).upper().strip()
                    if ':' in s2:
                        s2 = s2.split(':', 1)[-1]
                    return s2
                except Exception:
                    return None

            sym = _canon_symbol((payload.get('symbol') if isinstance(payload, dict) else None))
            action = (str(payload.get('action')).lower() if isinstance(payload, dict) and payload.get('action') is not None else None)
            # Some runners may signal close via boolean flags
            close_flag = False
            try:
                if isinstance(payload, dict):
                    close_flag = bool(payload.get('close') or payload.get('reduceOnly'))
                    # Also inspect nested 'response' structure
                    resp = payload.get('response') or {}
                    if isinstance(resp, dict):
                        close_flag = close_flag or bool(resp.get('close') or resp.get('reduceOnly'))
            except Exception:
                close_flag = False
            cd_ms = int(getattr(request.app.state, 'cooldown_after_close_ms', 0))
            if sym and cd_ms > 0 and (action == 'close' or close_flag):
                now_ms = int(time.time() * 1000)
                try:
                    getattr(request.app.state, '_cooldown_until_ms')[sym] = now_ms + cd_ms  # type: ignore[index]
                except Exception:
                    pass
                # Emit an optional event for observability
                em_ev2: AuroraEventLogger | None = getattr(request.app.state, 'events_emitter', None)
                if em_ev2:
                    try:
                        em_ev2.emit('AURORA.COOL_OFF', {'symbol': sym, 'until_ms': now_ms + cd_ms}, src='api')
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

# --- Overlay Control API ---
from fastapi import Body
import tempfile


def _overlay_dir() -> Path:
    return Path('profiles') / 'overlays'


def _overlay_active_path() -> Path:
    return _overlay_dir() / '_active_shadow.yaml'


def _overlay_backups_dir() -> Path:
    return _overlay_dir() / '_backups'


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile('w', delete=False, encoding='utf-8', dir=str(path.parent)) as tf:
        tf.write(content)
        tmp_name = tf.name
    Path(tmp_name).replace(path)


@app.post('/overlay/apply')
async def overlay_apply(request: Request, body: dict | str = Body(..., media_type='application/json'), _: bool = Depends(_xauth)):
    # Accept JSON or YAML string
    try:
        if isinstance(body, str):
            cfg = yaml.safe_load(body)
            serialized = body
        else:
            cfg = body
            serialized = yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True)
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid overlay body: {e}")

    # Validate minimal structure (at least dict)
    if not isinstance(cfg, dict):
        raise HTTPException(status_code=400, detail="Overlay must be an object")

    # Backup current
    act = _overlay_active_path()
    bdir = _overlay_backups_dir()
    bdir.mkdir(parents=True, exist_ok=True)
    version = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
    if act.exists():
        try:
            backup_path = bdir / f"shadow_{version}.yaml"
            backup_path.write_text(act.read_text(encoding='utf-8'), encoding='utf-8')
        except Exception:
            pass

    # Atomic write new overlay
    _atomic_write(act, serialized)

    # Emit event
    try:
        em: AuroraEventLogger | None = getattr(request.app.state, 'events_emitter', None)
        if em:
            em.emit('OBS.OVERLAY.APPLIED', {'version': version, 'active': str(act)})
    except Exception:
        pass

    return {"status": "ok", "version": version}


@app.get('/overlay/active')
async def overlay_active(_: bool = Depends(_xauth)):
    act = _overlay_active_path()
    if not act.exists():
        raise HTTPException(status_code=404, detail="No active overlay")
    st = act.stat()
    return {
        'path': str(act),
        'mtime': int(st.st_mtime),
        'version': time.strftime('%Y%m%d-%H%M%S', time.gmtime(st.st_mtime)),
        'body': act.read_text(encoding='utf-8'),
    }


@app.post('/overlay/rollback')
async def overlay_rollback(request: Request, body: dict = Body(...), _: bool = Depends(_xauth)):
    # body may contain {version: "..."} or {backup: "filename.yaml"}
    ver = (body or {}).get('version')
    bname = (body or {}).get('backup')
    bdir = _overlay_backups_dir()
    if ver:
        candidate = bdir / f"shadow_{ver}.yaml"
    elif bname:
        candidate = bdir / str(bname)
    else:
        raise HTTPException(status_code=400, detail="version or backup required")
    if not candidate.exists():
        raise HTTPException(status_code=404, detail="backup not found")
    _atomic_write(_overlay_active_path(), candidate.read_text(encoding='utf-8'))

    try:
        em: AuroraEventLogger | None = getattr(request.app.state, 'events_emitter', None)
        if em:
            em.emit('OBS.OVERLAY.ROLLED_BACK', {'to': candidate.name})
    except Exception:
        pass

    return {"status": "ok", "to": candidate.name}


# --- Orchestrator Introspection (readonly) ---
def _tail_file(path: Path, n: int) -> list[str]:
    if not path.exists():
        return []
    # Simple tail implementation
    lines = path.read_text(encoding='utf-8', errors='ignore').splitlines()
    return lines[-max(0, int(n)) :]


@app.get('/orchestrator/status')
async def orchestrator_status(_: bool = Depends(_xauth)):
    # Best-effort status snapshot
    status_path = Path('artifacts') / 'online_optuna_status.json'
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text(encoding='utf-8'))
            return {"status": data}
        except Exception:
            pass
    # Defaults
    return {
        "status": {
            "cycle": None,
            "explore_ratio": None,
            "ttl": None,
            "last_score": None,
            "last_gate": None,
        }
    }


@app.get('/orchestrator/events/tail')
async def orchestrator_events_tail(n: int = 200, _: bool = Depends(_xauth)):
    path = Path('artifacts') / 'online_optuna_events.jsonl'
    lines = _tail_file(path, n)
    return {"lines": lines}


# --- Gates Insight API (readonly) ---
def _iter_jsonl(path: Path):
    if not path.exists():
        return
    try:
        with path.open('r', encoding='utf-8', errors='ignore') as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    yield json.loads(line)
                except Exception:
                    continue
    except Exception:
        return


@app.get('/gates/counters')
async def gates_counters(minutes: int = 15):
    cutoff_ms = int(time.time() * 1000) - int(minutes * 60 * 1000)
    events = Path('logs') / 'aurora_events.jsonl'
    c = {
        'parent_gate_allow': 0,
        'parent_gate_deny': 0,
        'expected_net_reward_blocked': 0,
        'policy_allow': 0,
        'policy_deny': 0,
    }
    for ev in _iter_jsonl(events) or []:
        ts = int(ev.get('ts') or ev.get('ts_server') or 0)
        if ts < cutoff_ms:
            continue
        t = str(ev.get('type') or ev.get('code') or '')
        # Policy
        if t == POLICY_DECISION or t == 'POLICY.DECISION':
            try:
                dec = (ev.get('payload') or {}).get('decision')
                if dec == 'EXECUTE':
                    c['policy_allow'] += 1
                else:
                    c['policy_deny'] += 1
            except Exception:
                pass
        # Parent/ENR gates (best-effort types)
        if 'PARENT_GATE' in t and 'ALLOW' in t:
            c['parent_gate_allow'] += 1
        if 'PARENT_GATE' in t and ('DENY' in t or 'BLOCK' in t):
            c['parent_gate_deny'] += 1
        if 'EXPECTED_NET_REWARD' in t and ('LOW' in t or 'BLOCK' in t or 'DENY' in t):
            c['expected_net_reward_blocked'] += 1
    return {'window_min': minutes, 'counters': c}


@app.get('/gates/sample')
async def gates_sample(n: int = 10):
    events = Path('logs') / 'aurora_events.jsonl'
    samples: list[dict[str, Any]] = []
    lines = list(_iter_jsonl(events) or [])
    # iterate from end
    for ev in reversed(lines):
        t = str(ev.get('type') or ev.get('code') or '')
        if 'PARENT_GATE' in t or 'EXPECTED_NET_REWARD' in t:
            samples.append(ev)
        if len(samples) >= max(1, int(n)):
            break
    return {'count': len(samples), 'items': samples}


# --- Background SLI updater ---
async def _sli_update_loop(app: FastAPI):
    while True:
        try:
            # Update deny rate from recent counters window (reuse gates_counters)
            data = await gates_counters(minutes=15)
            c = data.get('counters', {})
            total = (c.get('policy_allow', 0) or 0) + (c.get('policy_deny', 0) or 0)
            deny_rate = (c.get('policy_deny', 0) or 0) / total if total > 0 else 0.0
            DENY_RATE_15M.set(deny_rate)
        except Exception:
            pass
        # Compute neutral p_cal streaks from recent MODEL.CALIBRATION
        try:
            ev_path = (getattr(app.state, 'session_dir', Path('logs')) / 'aurora_events.jsonl')
            last_by_symbol: dict[str, list[float]] = {}
            import json as _json
            lines: list[str] = []
            if ev_path.exists():
                try:
                    with ev_path.open('rb') as f:
                        f.seek(0, 2)
                        size = f.tell()
                        read = min(size, 512*1024)
                        f.seek(-read, 1)
                        chunk = f.read().decode('utf-8', errors='ignore')
                    lines = chunk.splitlines()
                except Exception:
                    try:
                        lines = ev_path.read_text(encoding='utf-8', errors='ignore').splitlines()
                    except Exception:
                        lines = []
            for ln in reversed(lines[-5000:]):
                try:
                    ev = _json.loads(ln)
                except Exception:
                    continue
                code = str(ev.get('event_code') or ev.get('code') or ev.get('type') or '').upper()
                if code != 'MODEL.CALIBRATION':
                    continue
                d = ev.get('details') or {}
                sym = str(d.get('symbol') or 'UNKNOWN')
                p = d.get('p_cal')
                if not isinstance(p, (int, float)):
                    continue
                arr = last_by_symbol.setdefault(sym, [])
                if len(arr) < 220:
                    arr.append(float(p))
            for sym, vals in last_by_symbol.items():
                if len(vals) >= 200 and all(abs(v - 0.5) < 1e-9 for v in vals[:200]):
                    MODEL_NEUTRAL_STREAK.labels(symbol=sym).set(1)
                else:
                    MODEL_NEUTRAL_STREAK.labels(symbol=sym).set(0)
        except Exception:
            pass
        # Other gauges are updated by respective components; keep placeholders
        try:
            await asyncio.sleep(float(os.getenv('AURORA_SLI_REFRESH_SEC', '7')))
        except Exception:
            await asyncio.sleep(7.0)


# --- Overlay control endpoints ---
class OverlayBody(BaseModel):
    overlay: dict


@app.get('/overlay/active')
async def overlay_active(_: bool = Depends(_xauth)):
    path: Path = getattr(app.state, 'overlay_path', Path('profiles/overlays/_active_shadow.yaml'))
    try:
        data = yaml.safe_load(path.read_text(encoding='utf-8')) if path.exists() else {}
    except Exception:
        data = {}
    return {"path": str(path), "overlay": data}


@app.post('/overlay/apply')
async def overlay_apply(body: OverlayBody, _: bool = Depends(_xauth)):
    path: Path = getattr(app.state, 'overlay_path', Path('profiles/overlays/_active_shadow.yaml'))
    path.parent.mkdir(parents=True, exist_ok=True)
    # backup current
    try:
        if path.exists():
            ts = time.strftime('%Y%m%d-%H%M%S', time.gmtime())
            backup = path.with_suffix(path.suffix + f'.{ts}.bak')
            shutil.copy2(path, backup)
            setattr(app.state, 'overlay_backup_last', backup)
    except Exception:
        pass
    # write new overlay atomically
    tmp = path.with_suffix(path.suffix + '.tmp')
    try:
        tmp.write_text(yaml.safe_dump(body.overlay, allow_unicode=True), encoding='utf-8')
        os.replace(tmp, path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'overlay write failed: {e}')
    # emit events
    try:
        em: AuroraEventLogger | None = getattr(app.state, 'events_emitter', None)
        if em:
            em.emit('OVERLAY.APPLY', {"path": str(path)})
            em.emit('PARENT_GATE.RELOAD', {"source": "overlay.apply"})
    except Exception:
        pass
    return {"status": "ok", "path": str(path)}


@app.post('/overlay/rollback')
async def overlay_rollback(_: bool = Depends(_xauth)):
    path: Path = getattr(app.state, 'overlay_path', Path('profiles/overlays/_active_shadow.yaml'))
    backup: Path | None = getattr(app.state, 'overlay_backup_last', None)
    if not (backup and backup.exists()):
        # find latest backup
        try:
            baks = sorted(path.parent.glob(path.name + '.*.bak'))
            backup = baks[-1] if baks else None
        except Exception:
            backup = None
    if not (backup and backup.exists()):
        raise HTTPException(status_code=404, detail='no backup found')
    try:
        shutil.copy2(backup, path)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f'rollback failed: {e}')
    try:
        em: AuroraEventLogger | None = getattr(app.state, 'events_emitter', None)
        if em:
            em.emit('OVERLAY.ROLLBACK', {"path": str(path), "from": str(backup)})
            em.emit('PARENT_GATE.RELOAD', {"source": "overlay.rollback"})
    except Exception:
        pass
    return {"status": "ok", "path": str(path), "from": str(backup)}

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


@app.get("/ops/model_status")
async def ops_model_status(_: bool = Depends(_ops_auth)):
    """Get model loading status for all symbols"""
    # Mock model status - in production read from actual model registry
    model_status = {
        "SOLUSDT": {
            "loaded": True,
            "features_ok": True,
            "calibrator_ok": True,
            "last_ts": time.time()
        },
        "SOONUSDT": {
            "loaded": True,
            "features_ok": True,
            "calibrator_ok": True,
            "last_ts": time.time()
        }
    }
    return {"status": "ok", "models": model_status}


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
