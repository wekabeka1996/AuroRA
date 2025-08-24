from __future__ import annotations
from typing import Optional, Dict, Any
from dataclasses import dataclass
import numpy as np
import time

try:  # optional cvxpy
    import cvxpy as cp  # type: ignore
    _HAS_CVXPY = True
except Exception:  # pragma: no cover
    _HAS_CVXPY = False

# Lightweight metrics shim (lazy import to avoid hard dep cycles)
try:  # pragma: no cover - metrics optional
    from living_latent.core.utils.metrics import gauge
except Exception:  # pragma: no cover
    def gauge(*args, **kwargs):  # type: ignore
        def _noop(v):
            return None
        return _noop

_dro_obj_g = gauge("aurora_dro_objective", "DRO-ES objective value")
_dro_rt_g  = gauge("aurora_dro_runtime_ms", "DRO-ES runtime (ms)")

@dataclass
class DROConfig:
    alpha: float = 0.10                 # CVaR level
    eps_mode: str = "fixed"            # "fixed" | "adaptive"
    eps: float = 0.02                  # ambiguity radius if fixed
    eps_vola_pct: float = 0.75         # if adaptive: percentile of vola/ACI → eps mapping (future use)
    solver: str = "OSQP"               # "OSQP"|"SCS"| "ANY"| "NONE"
    time_limit_ms: int = 400
    warm_start: bool = True
    use_cvxpy: bool = True             # master switch


# --- Public API ---

def dro_es_optimize(returns: np.ndarray,
                    cfg: DROConfig,
                    tail_snapshot: Optional[Dict[str, float]] = None) -> Dict[str, Any]:
    """Compute (approx) distributionally robust Expected Shortfall objective.

    Parameters
    ----------
    returns : np.ndarray
        Shape (n,) array of PnL returns (profit positive). Converted internally to losses.
    cfg : DROConfig
        Configuration including ES level alpha and ambiguity parameters.
    tail_snapshot : optional mapping with tail metrics ('xi','theta_e','lambda_U','es_alpha').

    Returns
    -------
    dict with keys: objective, cvar, eps, tail_proxy, status, runtime_ms
    """
    t0 = time.time()
    r = np.asarray(returns, dtype=float).reshape(-1)
    if r.size == 0:
        raise ValueError("dro_es_optimize: empty returns")

    alpha = float(cfg.alpha)
    losses = -r  # convert to losses

    # Tail proxy Γ
    xi = float(tail_snapshot.get("xi", 0.0)) if tail_snapshot else 0.0
    es_alpha = float(tail_snapshot.get("es_alpha", np.nan)) if tail_snapshot else np.nan
    if not np.isfinite(es_alpha):
        es_alpha = float(np.mean(np.maximum(losses, 0.0)))
    tail_proxy = max(0.0, xi) * max(1e-9, es_alpha)

    # eps selection
    if cfg.eps_mode == "fixed":
        eps = max(0.0, float(cfg.eps))
    else:  # adaptive simple heuristic
        base = 0.02
        eps = base * (1.0 + max(0.0, xi))

    use_cvx = bool(cfg.use_cvxpy and _HAS_CVXPY and cfg.solver.upper() != "NONE")
    if use_cvx:
        res = _solve_cvar_cvxpy(losses, alpha, cfg)
        cvar = res["cvar"]
        status = res["status"]
        runtime_ms = res["runtime_ms"]
    else:
        cvar = _compute_cvar_surrogate(losses, alpha)
        status = "FALLBACK"
        runtime_ms = (time.time() - t0) * 1000.0

    objective = float(cvar + eps * tail_proxy)

    _dro_obj_g(objective)
    _dro_rt_g(runtime_ms)

    return {
        "objective": objective,
        "cvar": float(cvar),
        "eps": float(eps),
        "tail_proxy": float(tail_proxy),
        "status": status,
        "runtime_ms": float(runtime_ms),
    }


# --- Internal helpers ---

def _solve_cvar_cvxpy(losses: np.ndarray, alpha: float, cfg: DROConfig) -> Dict[str, Any]:
    t0 = time.time()
    n = losses.size
    t = cp.Variable()  # VaR proxy
    u = cp.Variable(n, nonneg=True)
    constraints = [u >= losses - t]
    obj = t + (1.0 / ((1.0 - alpha) * n)) * cp.sum(u)
    prob = cp.Problem(cp.Minimize(obj), constraints)
    solver_map = {"OSQP": cp.OSQP, "SCS": cp.SCS}
    chosen = cfg.solver.upper()
    solver = solver_map.get(chosen, None)
    opts: Dict[str, Any] = {"max_iter": 10**6}
    if cfg.time_limit_ms:
        # best-effort time limit translation (seconds)
        opts["time_limit"] = max(1, int(cfg.time_limit_ms / 1000))
    if cfg.warm_start:
        opts["warm_start"] = True
    try:
        if solver is None and chosen in ("ANY", "OSQP", "SCS"):
            prob.solve(warm_start=cfg.warm_start, **opts)
        else:
            prob.solve(solver=solver, **opts)
    except Exception as e:  # pragma: no cover
        return {"cvar": float(_compute_cvar_surrogate(losses, alpha)), "status": f"FALLBACK_ERR:{e.__class__.__name__}", "runtime_ms": (time.time() - t0) * 1000.0}
    runtime_ms = (time.time() - t0) * 1000.0
    if prob.status not in ("optimal", "optimal_inaccurate"):
        return {"cvar": float(_compute_cvar_surrogate(losses, alpha)), "status": f"FALLBACK_{prob.status}", "runtime_ms": runtime_ms}
    cvar = float(prob.value)
    return {"cvar": cvar, "status": prob.status, "runtime_ms": runtime_ms}


def _compute_cvar_surrogate(losses: np.ndarray, alpha: float) -> float:
    n = losses.size
    if n == 0:
        return 0.0
    k = max(1, int(np.ceil((1.0 - alpha) * n)))
    sorted_losses = np.sort(losses)
    tail = sorted_losses[-k:]
    return float(np.mean(tail))


# --- Scenario generator (SEB+) ---

def get_scenarios(n: int,
                  regime: str,
                  sources: Dict[str, Any],
                  *,
                  p_ext: float = 0.10,
                  seed: int = 42) -> np.ndarray:
    """Return (n,) array of scenario returns mixing history + teacher extremes + EVT tail.

    Ensures >= p_ext fraction beyond VaR95 of historical distribution when history is present.
    """
    rng = np.random.default_rng(seed)
    hist = np.asarray(sources.get("history", np.array([], dtype=float))).reshape(-1)
    teacher = np.asarray(sources.get("teacher_extremes", np.array([], dtype=float))).reshape(-1)
    xi_hat = float(sources.get("xi_hat", 0.0))
    scale_tail = float(sources.get("scale_tail", 1.0))

    parts: list[np.ndarray] = []
    # 1) bootstrap central mass
    if hist.size > 0:
        idx = rng.integers(0, hist.size, size=max(1, int(n * (1.0 - p_ext))))
        parts.append(hist[idx])
    # 2) teacher extremes
    if teacher.size > 0:
        tcount = max(0, int(n * p_ext // 2))
        if tcount > 0:
            tidx = rng.integers(0, teacher.size, size=tcount)
            parts.append(teacher[tidx])
    # 3) EVT synthetic heavy losses (convert to negative returns)
    ecount = max(0, int(n * p_ext) - sum(p.size for p in parts))
    if ecount > 0:
        pareto_losses = _evtp_pareto_losses(ecount, xi_hat=xi_hat, scale=scale_tail, rng=rng)
        parts.append(-pareto_losses)
    scenarios = np.concatenate(parts) if parts else rng.normal(0.0, 1e-3, size=n)
    if scenarios.size < n:
        pad = rng.choice(scenarios, size=(n - scenarios.size))
        scenarios = np.concatenate([scenarios, pad])
    elif scenarios.size > n:
        scenarios = scenarios[:n]
    # enforce tail fraction relative to VaR95 if history sufficiently large
    if hist.size > 100:
        q95 = np.quantile(hist, 0.95)
        frac = (scenarios > q95).mean()
        if frac < p_ext and teacher.size > 0:
            need = int(np.ceil((p_ext - frac) * n))
            inj = rng.choice(teacher, size=need)
            scenarios[:need] = inj
    return scenarios


def _evtp_pareto_losses(m: int, xi_hat: float, scale: float, rng) -> np.ndarray:
    xi = max(1e-6, float(xi_hat))
    u = rng.random(m)
    return scale * (np.power(1.0 - u, -xi) - 1.0)

__all__ = [
    "DROConfig",
    "dro_es_optimize",
    "get_scenarios",
]
