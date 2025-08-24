from __future__ import annotations
import argparse
from typing import Optional, Any, Dict
from fastapi import FastAPI, Response, status
from pydantic import BaseModel
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest, CollectorRegistry
import uvicorn
from pathlib import Path

from living_latent.service.context import CTX

try:  # ruamel optional
    from ruamel.yaml import YAML  # type: ignore
except Exception:  # pragma: no cover
    YAML = None  # type: ignore

# ---------- Pydantic models ----------
class Health(BaseModel):
    status: str = "ok"

class Ready(BaseModel):
    ready: bool
    profile: str
    state: Optional[str] = None

class StateSnapshot(BaseModel):
    profile: str
    state: Optional[str]
    decision: Optional[str]
    kappa_plus: Optional[float]
    p95_surprisal: Optional[float]
    coverage_ema: Optional[float]
    latency_p95: Optional[float]
    alpha: Optional[float]
    alpha_target: Optional[float]

def _build_state_snapshot() -> StateSnapshot:
    acc = CTX.get_acceptance()
    profile = CTX.get_profile()
    state = None
    decision = None
    kappa_plus = p95_surprisal = coverage_ema = latency_p95 = None
    alpha = alpha_target = None
    if acc is not None:
        try:
            st: Dict[str, Any] = acc.stats()  # type: ignore
        except Exception:
            st = {}
        state = st.get("current_state") or getattr(getattr(acc, "hysteresis_gate", None), "current_state", None)
        decision = st.get("last_decision")
        kappa_plus = st.get("kappa_plus_p50") or st.get("kappa_plus_last")
        p95_surprisal = st.get("surprisal_p95")
        coverage_ema = st.get("coverage_ema")
        latency_p95 = st.get("latency_p95")
        alpha = st.get("alpha")
        alpha_target = st.get("alpha_target")
    return StateSnapshot(
        profile=profile,
        state=state,
        decision=decision,
        kappa_plus=kappa_plus,
        p95_surprisal=p95_surprisal,
        coverage_ema=coverage_ema,
        latency_p95=latency_p95,
        alpha=alpha,
        alpha_target=alpha_target,
    )

def create_app() -> FastAPI:
    app = FastAPI(title="AURORA Unified API", version="1.0")

    @app.get("/healthz", response_model=Health)
    def healthz():  # pragma: no cover - trivial
        return Health()

    @app.get("/readyz", response_model=Ready)
    def readyz():
        acc = CTX.get_acceptance()
        snap = _build_state_snapshot()
        return Ready(ready=(acc is not None), profile=snap.profile, state=snap.state)

    @app.get("/state", response_model=StateSnapshot)
    def state():
        return _build_state_snapshot()

    @app.get("/metrics")
    def metrics():
        reg: Optional[CollectorRegistry] = CTX.get_registry()
        if reg is None:
            return Response(content="# no registry\n", media_type=CONTENT_TYPE_LATEST, status_code=status.HTTP_200_OK)
        data = generate_latest(reg)
        return Response(content=data, media_type=CONTENT_TYPE_LATEST)

    return app

def _load_cfg(path: str):
    p = Path(path)
    if not p.exists():
        raise SystemExit(f"Config not found: {path}")
    if YAML is None:
        import yaml as pyyaml  # type: ignore
        with open(p, "r", encoding="utf-8") as f:
            return pyyaml.safe_load(f)
    yaml = YAML(typ="safe")
    return yaml.load(p.read_text(encoding="utf-8"))

def main():  # pragma: no cover (CLI entry)
    parser = argparse.ArgumentParser(description="Run unified AURORA API service")
    parser.add_argument("--profile", default="default")
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=9100)
    parser.add_argument("--config", default="living_latent/cfg/master.yaml")
    args = parser.parse_args()

    cfg = _load_cfg(args.config)
    profiles = cfg.get("profiles", {})
    if args.profile not in profiles:
        raise SystemExit(f"Profile '{args.profile}' not found in config")
    CTX.set_profile(args.profile)
    # If no registry injected externally, create empty one to satisfy /metrics
    if CTX.get_registry() is None:
        CTX.set_registry(CollectorRegistry())

    app = create_app()
    uvicorn.run(app, host=args.host, port=args.port, log_level="info")

if __name__ == "__main__":  # pragma: no cover
    main()
