
import os
import sys
import yaml
import asyncio
import uvicorn
from fastapi import FastAPI, HTTPException, Request
from contextlib import asynccontextmanager
from fastapi.responses import RedirectResponse, HTMLResponse, JSONResponse
from pathlib import Path
from pydantic import BaseModel
from prometheus_client import make_asgi_app, Histogram, Gauge, Counter

# Ensure project root is on sys.path when running directly (python api/service.py)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from trading.main_loop import TradingSystem
from core.aurora.pretrade import gate_latency, gate_slippage, gate_expected_return, gate_trap
from core.scalper.calibrator import IsotonicCalibrator, CalibInput
from core.scalper.sprt import SPRT, SprtConfig
from core.scalper.trap import TrapWindow
from common.config import AppConfig, AuroraConfig, RiskConfig, SlippageConfig, LoggingConfig, PolicyShimConfig, ChatConfig
from common.config import load_sprt_cfg
from common.events import EventEmitter

# Read version from VERSION file
def get_version():
    try:
        version_file = os.path.join(PROJECT_ROOT, 'VERSION')
        with open(version_file, 'r') as f:
            return f.read().strip()
    except:
        return os.getenv('AURORA_VERSION', 'unknown')

# --- Pydantic моделі для валідації запитів та відповідей ---
class PredictionRequest(BaseModel):
    # У реальності тут можуть бути id користувача, символ активу і т.д.
    # Для нашого прикладу, фічі передаються напряму.
    features: list[float]

class PredictionResponse(BaseModel):
    forecast: float
    interval_lower: float
    interval_upper: float
    weights: list[float]
    kappa_plus: float
    regime: int
    latency_ms: float

# --- Minimal pretrade/posttrade models ---
class PretradeCheckRequest(BaseModel):
    ts: int | None = None
    req_id: str | None = None
    account: dict
    order: dict
    market: dict
    risk_tags: list[str] | None = None
    fees_bps: float | None = None

class PretradeCheckResponse(BaseModel):
    allow: bool
    max_qty: float
    risk_scale: float = 1.0
    cooldown_ms: int = 0
    reason: str = "ok"
    hard_gate: bool = False
    quotas: dict | None = None
    observability: dict | None = None

# --- Ініціалізація ---

# Завантажуємо конфігурацію шляху за умовчанням (v4_min), але фактичне завантаження переносимо в lifespan
CONFIG_PATH = os.path.join(PROJECT_ROOT, 'configs', 'v4_min.yaml')
config = None  # populated in lifespan

# Створюємо екземпляр FastAPI
VERSION = get_version()
@asynccontextmanager
async def lifespan(app: FastAPI):
    # startup: load configs and initialize shared components
    try:
        cfg = yaml.safe_load(open(CONFIG_PATH, 'r', encoding='utf-8'))
    except Exception:
        cfg = {}
    # expose raw cfg and derived sprt cfg
    try:
        sprt_cfg = load_sprt_cfg(cfg)
    except Exception:
        sprt_cfg = None
    app.state.cfg = cfg
    app.state.sprt_cfg = sprt_cfg
    # Event emitter and TRAP window
    try:
        emitter_path = ((cfg or {}).get('logging') or {}).get('path', 'logs/events.jsonl')
    except Exception:
        emitter_path = 'logs/events.jsonl'
    app.state.events_emitter = EventEmitter(path=Path(emitter_path))
    trap_cfg = (cfg or {}).get('trap') or {}
    window_s = float(trap_cfg.get('window_s', 2.0))
    levels = int(trap_cfg.get('levels', 5))
    app.state.trap_window = TrapWindow(window_s=window_s, levels=levels)
    # Initialize trading system lazily; ignore failure (health will report unhealthy)
    try:
        ts = TradingSystem(cfg)
    except Exception:
        ts = None
    app.state.trading_system = ts
    yield
    # shutdown: best-effort cleanup
    ts = getattr(app.state, 'trading_system', None)
    if ts is not None:
        app.state.trading_system = None
    emitter = getattr(app.state, 'events_emitter', None)
    if emitter is not None and hasattr(emitter, 'close'):
        try:
            emitter.close()
        except Exception:
            pass

app = FastAPI(
    title="AURORA Trading API",
    version=VERSION,
    description="API for the unified certifiable regime-aware trading system.",
    lifespan=lifespan,
)

# Пізня ініціалізація торгової системи в події старту застосунку
# Уникаємо важких операцій при імпорті модуля
_TRADING_SYSTEM_KEY = "trading_system"
_EVENTS_KEY = "events_emitter"
_TRAP_WINDOW_KEY = "trap_window"

# --- Метрики для Prometheus ---

# Створюємо ASGI додаток для метрик
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Визначаємо метрики, які будемо відстежувати
LATENCY = Histogram('aurora_prediction_latency_ms', 'Prediction latency in milliseconds', buckets=(1,2,5,7.5,10,15,25,50,75,100,150,250))
KAPPA_PLUS = Gauge('aurora_kappa_plus', 'Current kappa plus uncertainty metric')
REGIME = Gauge('aurora_regime', 'Current detected market regime')
REQUESTS = Counter('aurora_prediction_requests_total', 'Total prediction requests')

# --- API Endpoints ---

@app.post("/predict", response_model=PredictionResponse)
async def predict(request: PredictionRequest):
    """
    Основний ендпоінт для отримання прогнозу та торгового рішення.
    """
    try:
        # Виконуємо прогноз з таймаутом, щоб гарантувати SLA
        ts = getattr(app.state, 'trading_system', None)
        if ts is None:
            raise HTTPException(status_code=503, detail="Trading system not initialized")

        result = await asyncio.wait_for(
            asyncio.to_thread(ts.predict, request.model_dump()),
            timeout=((getattr(app.state, 'cfg', {}) or {}).get('trading', {}) or {}).get('max_latency_ms', 1000) / 1000.0
        )
        # Оновлюємо метрики Prometheus
        REQUESTS.inc()
        LATENCY.observe(result['latency_ms'])
        KAPPA_PLUS.set(result['kappa_plus'])
        REGIME.set(result['regime'])
        return PredictionResponse(
            forecast=result['forecast'],
            interval_lower=result['interval'][0],
            interval_upper=result['interval'][1],
            weights=result['weights'].tolist() if hasattr(result['weights'], 'tolist') else result['weights'],
            kappa_plus=result['kappa_plus'],
            regime=result['regime'],
            latency_ms=result['latency_ms']
        )
    except asyncio.TimeoutError:
        slo = ((getattr(app.state, 'cfg', {}) or {}).get('trading', {}) or {}).get('max_latency_ms', 1000)
        raise HTTPException(status_code=503, detail=f"Prediction timeout: Service busy or latency SLO ({slo}ms) exceeded.")
    except Exception as e:
        # Логування помилки
        print(f"[ERROR] Prediction failed: {e}")
        raise HTTPException(status_code=500, detail=f"Internal Server Error: {e}")

@app.get("/version")
async def version():
    """
    Ендпоінт для отримання версії системи.
    """
    return {
        "version": VERSION,
        "build_info": {
            "aurora_version": os.getenv('AURORA_VERSION', VERSION),
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        }
    }

@app.get("/healthz")
async def healthz():
    """
    Kubernetes-style health check alias for compatibility with previous scripts.
    Mirrors /health behavior.
    """
    return await health()

@app.get("/")
async def root():
    """Redirect to interactive docs to make browser access friendlier."""
    # FastAPI returns 404 by default on '/', so provide a friendly landing page/redirect
    return RedirectResponse(url="/docs", status_code=307)

@app.get("/health")
async def health():
    """
    Ендпоінт для перевірки стану сервісу.
    """
    # Проста перевірка, чи завантажена модель
    ts = getattr(app.state, 'trading_system', None)
    model_loaded = ts is not None and ts.student is not None and ts.router is not None
    
    if model_loaded:
        return {"status": "healthy", "models_loaded": True}
    else:
        raise HTTPException(status_code=503, detail={"status": "unhealthy", "models_loaded": False})

@app.post("/pretrade/check", response_model=PretradeCheckResponse)
async def pretrade_check(request: Request, req: PretradeCheckRequest):
    """Lightweight pre-trade risk/gate check used by WiseScalp.
    For now uses simple rules and always allow in shadow/paper.
    """
    try:
        mode = (req.account or {}).get('mode', os.getenv('AURORA_MODE', 'shadow'))
        max_qty = float((req.order or {}).get('qty', 0.0) or 0.0)
        m = req.market or {}
        # Inputs possibly sent by runner
        latency_ms = float(m.get('latency_ms', 0.0) or 0.0)
        slip_bps_est = float(m.get('slip_bps_est', 0.0) or 0.0)
        a_bps = float(m.get('a_bps', 0.0) or 0.0)
        b_bps = float(m.get('b_bps', 0.0) or 0.0)
        score = float(m.get('score', 0.0) or 0.0)
        regime = str(m.get('mode_regime', 'normal'))
        spread_bps = float(m.get('spread_bps', 0.0) or 0.0)
        sprt_samples = m.get('sprt_samples')  # optional short list of observations
        # Optional TRAP inputs (synthetic for tests; runner can provide real ones)
        trap_cancel_deltas = m.get('trap_cancel_deltas')
        trap_add_deltas = m.get('trap_add_deltas')
        trap_trades_cnt = m.get('trap_trades_cnt')

        # Config thresholds using v4_min defaults where available
        # Fall back to production.yaml aurora.latency_guard_ms if present
        lmax_ms = None
        try:
            # If v4_min.yaml was loaded elsewhere, prefer env overrides; otherwise default
            lmax_ms = int(os.getenv('AURORA_LMAX_MS', '30'))
        except Exception:
            lmax_ms = 30

        emitter: EventEmitter | None = getattr(request.app.state, 'events_emitter', None)
        # TRAP window from app state
        tw: TrapWindow | None = getattr(request.app.state, 'trap_window', None)

        # Enforce health in prod: fail-closed on unhealthy
        allow = True
        reason = 'ok'
        if mode == 'prod':
            ts = getattr(request.app.state, 'trading_system', None)
            if ts is None or ts.student is None or ts.router is None:
                allow, reason = False, 'service_unhealthy'

        reasons: list[str] = []
        # Latency guard (fail-closed style)
        if allow and not gate_latency(latency_ms=latency_ms, lmax_ms=float(lmax_ms), reasons=reasons):
            allow, reason = False, 'latency_guard'
            if emitter:
                emitter.emit(
                    type="HEALTH.LATENCY_HIGH",
                    severity="warning",
                    code="HEALTH.LATENCY_HIGH",
                    payload={"latency_ms": latency_ms, "lmax_ms": float(lmax_ms)},
                )
        # TRAP guard (continuous z-score fake-wall detection)
        trap_obs = None
        if allow and trap_cancel_deltas is not None and trap_add_deltas is not None and trap_trades_cnt is not None:
            try:
                z_threshold = float(os.getenv('AURORA_TRAP_Z_THRESHOLD', '1.64'))
                cancel_pctl = int(os.getenv('AURORA_TRAP_CANCEL_PCTL', '90'))
            except Exception:
                z_threshold, cancel_pctl = 1.64, 90
            # Optional conflict rule inputs (signs)
            obi_sign = m.get('obi_sign')
            tfi_sign = m.get('tfi_sign')
            # Ensure lists of floats
            cancel_d = [float(x) for x in trap_cancel_deltas]
            add_d = [float(x) for x in trap_add_deltas]
            trades_cnt = int(trap_trades_cnt)
            assert tw is not None
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
            trap_obs = {
                'trap_z': metrics.trap_z,
                'cancel_rate': metrics.cancel_rate,
                'repl_rate': metrics.repl_rate,
                'n_trades': metrics.n_trades,
            }
            if not allow_trap:
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
        # Slippage guard against eta * b
        eta = None
        try:
            eta = float(os.getenv('AURORA_SLIP_ETA', '0.3'))
        except Exception:
            eta = 0.3
        if allow and not gate_slippage(slip_bps=slip_bps_est, b_bps=b_bps, eta_fraction_of_b=eta, reasons=reasons):
            allow, reason = False, 'slippage_guard'
            if emitter:
                emitter.emit(
                    type="AURORA.RISK_WARN",
                    severity="warning",
                    code="AURORA.SLIPPAGE_GUARD",
                    payload={"slip_bps": slip_bps_est, "b_bps": b_bps, "eta": eta},
                )

        # Optional SPRT reconfirmation before expected-return gate
        sprt_decision = None
        sprt_llr = None
        sprt_n = None
        if allow and sprt_samples is not None:
            try:
                # Use merged SPRT config from app state overrides
                scfg = getattr(request.app.state, 'sprt_cfg', None)
                if scfg is not None and getattr(scfg, 'enabled', True):
                    sigma = scfg.sigma
                    A = scfg.A
                    B = scfg.B
                    max_obs = scfg.max_obs
                else:
                    sigma, A, B, max_obs = 1.0, 2.0, -2.0, 10
                cfg = SprtConfig(mu0=0.0, mu1=score, sigma=sigma, A=A, B=B, max_obs=max_obs)
                sprt = SPRT(cfg)
                sprt_decision = sprt.run([float(x) for x in sprt_samples])
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

        # Expected-return gate via calibrator
        if allow:
            fees_bps = float(req.fees_bps or 0.0)
            cal = IsotonicCalibrator()
            # Calibrator might be unfitted in live; we use fallback sigmoid behaviour by not fitting.
            ci = CalibInput(score=score, a_bps=a_bps, b_bps=b_bps, fees_bps=fees_bps, slip_bps=slip_bps_est, regime=regime)
            out = cal.e_pi_bps(ci)
            pi_min = None
            try:
                pi_min = float(os.getenv('AURORA_PI_MIN_BPS', '2.0'))
            except Exception:
                pi_min = 2.0
            if not gate_expected_return(e_pi_bps=out.e_pi_bps, pi_min_bps=pi_min, reasons=reasons):
                allow, reason = False, 'expected_return_gate'
                if emitter:
                    emitter.emit(
                        type="AURORA.RISK_WARN",
                        severity="warning",
                        code="AURORA.EXPECTED_RETURN_LOW",
                        payload={"e_pi_bps": out.e_pi_bps, "pi_min_bps": pi_min},
                    )

        # Spread hard check remains as advisory unless extreme
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
            'trap': trap_obs,
            'sprt': {
                'decision': sprt_decision,
                'llr': sprt_llr,
                'n_obs': sprt_n,
            },
            'reasons': reasons,
        }
        quotas = {'trades_pm_left': 999, 'symbol_exposure_left_usdt': 1e12}
        # Policy decision event
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
        return PretradeCheckResponse(allow=allow, max_qty=max_qty, reason=reason, observability=obs, quotas=quotas)
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

@app.post("/posttrade/log")
async def posttrade_log(payload: dict):
    """Accept post-trade execution log; currently just ACKs."""
    try:
        return {"status": "ok"}
    except Exception as e:
        raise HTTPException(status_code=422, detail=str(e))

# --- Запуск сервісу ---

if __name__ == '__main__':
    # Запуск з використанням uvicorn, як зазначено в Додатку А
    host = ((app.state.cfg or {}).get('api', {}) or {}).get('host', '0.0.0.0') if hasattr(app.state, 'cfg') else '0.0.0.0'
    port = ((app.state.cfg or {}).get('api', {}) or {}).get('port', 8000) if hasattr(app.state, 'cfg') else 8000
    uvicorn.run(app, host=host, port=port)

# Lifespan handles startup/shutdown; removed deprecated on_event hooks.