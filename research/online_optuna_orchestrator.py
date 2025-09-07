# -*- coding: utf-8 -*-
"""Online parameter orchestrator for live feed + shadow orders.
- Runs exploit/explore cycles and writes overlay atomically.
- Reads simple SLI/TCA signals (pluggable) to compute score.
- No Docker. Safe by design: enforces hard gates before accepting a new best.
"""
import argparse, os, json, time, random, math, pathlib, shutil
from typing import Dict, Any

try:
    import yaml
except Exception as e:
    raise SystemExit("pyyaml is required: pip install pyyaml")

DEFAULT_BOUNDS = {
    "sizing.limits.max_notional_usd": (25, 500, int),
    "sizing.kelly_scaler": (0.02, 0.25, float),
    "universe.ranking.top_n": (3, 25, int),
    "execution.router.spread_limit_bps": (5, 25, int),
    "execution.sla.max_latency_ms": (100, 350, int),
    "reward.ttl_minutes": (10, 60, int),
    "reward.take_profit_bps": (10, 60, int),
    "reward.stop_loss_bps": (15, 120, int),
    "reward.be_break_even_bps": (4, 20, int),
    "tca.adverse_window_s": (5, 60, int),
}

HARD_GATES = {
    "deny_rate_max": 0.35,
    "latency_p99_max": 300.0,
    "ece_max": 0.05,
    "cvar95_min": -0.02,
}

# Optional freeze flag path for SLO watchdog to signal explore freeze and overlay rollback
FREEZE_FLAG_PATH = os.environ.get("AURORA_ORCH_FREEZE_FLAG", "artifacts/freeze_explore.flag")


def _atomic_write(path: str, data: str):
    p = pathlib.Path(path)
    tmp = p.with_suffix(p.suffix + ".tmp")
    tmp.write_text(data, encoding="utf-8")
    os.replace(tmp, p)


def _apply_overrides(base: Dict[str, Any], params: Dict[str, Any]):
    cfg = json.loads(json.dumps(base))
    for k, v in params.items():
        node = cfg
        keys = k.split('.')
        for part in keys[:-1]:
            node = node.setdefault(part, {})
        node[keys[-1]] = v
    return cfg


def _mutate(params: Dict[str, Any]) -> Dict[str, Any]:
    out = dict(params)
    for k, (lo, hi, tp) in DEFAULT_BOUNDS.items():
        if k not in out:  # add missing with mid
            if tp is int:
                out[k] = int((lo + hi) // 2)
            else:
                out[k] = (lo + hi) / 2.0
        # small local mutation
        if tp is int:
            step = max(1, (hi - lo) // 20)
            out[k] = int(max(lo, min(hi, out[k] + random.randint(-step, step))))
        else:
            span = (hi - lo) * 0.05
            out[k] = max(lo, min(hi, out[k] + random.uniform(-span, span)))
    return out


def _mids_from_bounds() -> Dict[str, Any]:
    mids: Dict[str, Any] = {}
    for k, (lo, hi, tp) in DEFAULT_BOUNDS.items():
        if tp is int:
            mids[k] = int((lo + hi) // 2)
        else:
            mids[k] = (lo + hi) / 2.0
    return mids


def _read_base_profile(path: str) -> Dict[str, Any]:
    return yaml.safe_load(open(path, 'r', encoding='utf-8'))


def _score(metrics: Dict[str, float]) -> float:
    # Minimal viable score; all keys optional
    sharpe = metrics.get("sharpe", 0.0)
    ret = metrics.get("return_adj", 0.0)
    kelly_eff = metrics.get("kelly_eff", 0.0)
    tca = metrics.get("tca_cost_bps", 0.0) / 10000.0
    # Heavier penalty for transaction costs to be conservative
    return 0.5 * sharpe + 0.2 * ret + 0.2 * max(0.0, kelly_eff) - 0.2 * tca


def _violates_gates(metrics: Dict[str, float]) -> str:
    if metrics.get("deny_rate", 0.0) > HARD_GATES["deny_rate_max"]:
        return "deny_rate"
    if metrics.get("latency_p99", 0.0) > HARD_GATES["latency_p99_max"]:
        return "latency_p99"
    if metrics.get("ece", 1.0) > HARD_GATES["ece_max"]:
        return "ece"
    if metrics.get("cvar95", 0.0) < HARD_GATES["cvar95_min"]:
        return "cvar95"
    return ""


def _harvest_metrics(log_dir: str) -> Dict[str, float]:
    import glob, json as _json
    vals = {"deny_rate": 0.0, "latency_p99": 0.0, "ece": 0.0, "cvar95": 0.0, "tca_cost_bps": 0.0}
    files = sorted(glob.glob(os.path.join(log_dir, "*.jsonl")))
    if not files:
        return vals

    considered = denied = 0
    lat = []
    eces = []
    cvars = []
    tca_costs = []

    # читаємо лише хвіст останніх файлов
    for fp in files[-10:]:
        try:
            with open(fp, "r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()[-200:]
        except Exception:
            continue
        for ln in lines:
            try:
                ev = _json.loads(ln)
            except Exception:
                continue

            tag = ev.get("event") or ev.get("type") or ev.get("category") or ev.get("code") or ""
            tag = str(tag).upper()

            # POLICY: considered/denied
            if "POLICY.DECISION" in tag or (tag.startswith("POLICY") and ("decision" in ev or "status" in ev)):
                considered += 1
                dec = (ev.get("decision") or ev.get("status") or "").upper()
                if dec == "DENY":
                    denied += 1

            # EXEC latency
            if tag.startswith("EXEC") or "ORDER.ACK" in tag or "ORDER.SUBMIT" in tag:
                v = ev.get("latency_ms") or ev.get("roundtrip_ms") or (ev.get("details") or {}).get("latency_ms")
                if isinstance(v, (int, float)):
                    lat.append(float(v))

            # CALIBRATION
            if tag.startswith("CALIBRATION"):
                v = ev.get("ece") or (ev.get("details") or {}).get("ece")
                if isinstance(v, (int, float)):
                    eces.append(float(v))

            # RISK / GOVERNANCE CVaR
            if tag.startswith("RISK") or tag.startswith("GOVERNANCE"):
                v = ev.get("cvar95") or ev.get("cvar_95") or (ev.get("details") or {}).get("cvar95")
                if isinstance(v, (int, float)):
                    cvars.append(float(v))

            # TCA components
            if tag.startswith("TCA"):
                s = ev.get("slippage_bps") or (ev.get("details") or {}).get("slippage_bps")
                f = ev.get("fees_bps") or (ev.get("details") or {}).get("fees_bps")
                a = ev.get("adverse_bps") or (ev.get("details") or {}).get("adverse_bps")
                parts = []
                for x in (s, f, a):
                    if isinstance(x, (int, float)):
                        parts.append(float(x))
                if parts:
                    tca_costs.append(sum(parts))

    if considered > 0:
        vals["deny_rate"] = denied / considered
    if lat:
        lat_sorted = sorted(lat)
        idx = max(0, int(0.99 * len(lat_sorted)) - 1)
        vals["latency_p99"] = lat_sorted[idx]
    if eces:
        vals["ece"] = sum(eces) / len(eces)
    if cvars:
        vals["cvar95"] = min(cvars)
    if tca_costs:
        vals["tca_cost_bps"] = sum(tca_costs) / len(tca_costs)
    return vals


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--overlay-path", required=True)
    ap.add_argument("--base-profile", required=True)
    ap.add_argument("--logs-dir", default="logs")
    ap.add_argument("--ttl-minutes", type=int, default=10)
    ap.add_argument("--explore-ratio", type=float, default=0.1)
    ap.add_argument("--events-jsonl", default="artifacts/online_optuna_events.jsonl")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.events_jsonl) or ".", exist_ok=True)

    base = _read_base_profile(args.base_profile)
    # Initialize best params at mid-range values for faster convergence
    best_params: Dict[str, Any] = _mids_from_bounds()
    best_score = float("-inf")

    cycle = 0
    # For demonstration, run a small number of cycles if TTL is small
    while True:
        cycle += 1
        # Check freeze flag from SLO watchdog
        freeze = os.path.exists(FREEZE_FLAG_PATH)
        if freeze:
            explore = False
            params = {}
            cfg = base
            mode = "freeze"
        else:
            explore = (random.random() < args.explore_ratio)
            params = _mutate(best_params) if explore else best_params
            cfg = _apply_overrides(base, params)
            mode = "explore" if explore else "exploit"

        _atomic_write(args.overlay_path, yaml.safe_dump(cfg, allow_unicode=True))

        # Sleep for TTL period with heartbeat every 10 seconds
        sleep_time = max(1.0, args.ttl_minutes * 60)
        start_time = time.time()
        next_heartbeat = start_time + 10.0
        
        while time.time() - start_time < sleep_time:
            now = time.time()
            if now >= next_heartbeat:
                # Log heartbeat to same events file
                heartbeat_rec = {
                    "ts": now,
                    "cycle": cycle,
                    "mode": mode,
                    "event": "ORCH.HEARTBEAT",
                    "elapsed_s": round(now - start_time, 1),
                    "remaining_s": round(sleep_time - (now - start_time), 1)
                }
                with open(args.events_jsonl, "a", encoding="utf-8") as f:
                    f.write(json.dumps(heartbeat_rec, ensure_ascii=False) + "\n")
                next_heartbeat = now + 10.0
            
            time.sleep(1.0)  # Check every second
        metrics = _harvest_metrics(args.logs_dir)
        g = _violates_gates(metrics)
        score = _score(metrics)

        rec = {
            "ts": time.time(),
            "cycle": cycle,
            "mode": mode,
            "params": params,
            "metrics": metrics,
            "score": score,
            "gate": g or "ok",
        }
        with open(args.events_jsonl, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

        if g:
            # reject this cycle and do not update best
            continue
        if score > best_score:
            best_score, best_params = score, params


if __name__ == "__main__":
    main()
