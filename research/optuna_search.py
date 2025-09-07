# -*- coding: utf-8 -*-
import json, os, time, argparse, pathlib, subprocess, tempfile, yaml
import optuna
from optuna.samplers import TPESampler
from optuna.pruners import MedianPruner

SEARCH_SPACE = {
    "sizing.limits.max_notional_usd": (50, 2000, int),
    "sizing.limits.leverage_max": (1, 5, int),
    "sizing.kelly_scaler": (0.05, 0.5, float),
    "universe.ranking.top_n": (3, 25, int),
    "execution.router.spread_limit_bps": (1, 20, int),
    "execution.sla.max_latency_ms": (50, 400, int),
    "tca.adverse_window_s": (5, 60, int),
    "reward.ttl_minutes": (5, 90, int),
    "reward.take_profit_bps": (5, 60, int),
    "reward.stop_loss_bps": (8, 100, int),
    "reward.be_break_even_bps": (2, 20, int),
}

HARD_LIMITS = {
    "cvar95_min": -0.12,        # CVaR_95 ≥ -12% (more realistic)
    "max_dd_max": 0.25,         # MaxDrawdown ≤ 25% (more realistic)
    "latency_p99_max": 300.0,   # ms
    "deny_rate_max": 0.35,      # 35%
    "ece_max": 0.05,
}


def apply_overrides(base_cfg: dict, params: dict):
    cfg = json.loads(json.dumps(base_cfg))
    for k, v in params.items():
        node = cfg
        parts = k.split('.')
        for p in parts[:-1]:
            node = node.setdefault(p, {})
        node[parts[-1]] = v
    return cfg


def run_replay(profile_dict: dict, replay_dir: str, workdir: str) -> dict:
    """Виклик існуючого інструменту реплею.
    Очікується, що tools/replay.py приймає `--profile-json <path>` і `--replay-dir` та зберігає метрики у JSON.
    Якщо інтерфейси інші — відредагувати виклик і адаптер парсингу нижче.
    """
    prof_path = os.path.join(workdir, "profile_trial.yaml")
    with open(prof_path, "w", encoding="utf-8") as f:
        yaml.safe_dump(profile_dict, f, allow_unicode=True)

    out_json = os.path.join(workdir, "metrics.json")
    cmd = [
        "python", "-m", "tools.replay",
        "--replay-dir", replay_dir,
        "--profile", prof_path,
        "--out-json", out_json,
        "--strict", "false",
    ]
    subprocess.run(cmd, check=True)
    with open(out_json, "r", encoding="utf-8") as f:
        m = json.load(f)

    # Адаптувати ключі під фактичний вивід tools/replay
    return {
        "sharpe": m.get("sharpe", 0.0),
        "return_adj": m.get("return_after_costs", 0.0),
        "tca_slip_bps": m.get("tca", {}).get("slippage_bps", 0.0),
        "tca_fees_bps": m.get("tca", {}).get("fees_bps", 0.0),
        "tca_adv_bps": m.get("tca", {}).get("adverse_bps", 0.0),
        "cvar95": m.get("risk", {}).get("cvar_95", -1.0),
        "max_dd": m.get("risk", {}).get("max_drawdown", 1.0),
        "latency_p99": m.get("exec", {}).get("latency_p99_ms", 1e9),
        "deny_rate": m.get("policy", {}).get("deny_rate_15m", 1.0),
        "ece": m.get("calibration", {}).get("ece", 1.0),
        "xai_top_why": m.get("xai", {}).get("top_why", []),
    }


def score(m: dict) -> float:
    # Пріоритет: безпека → якість → дохідність → витрати
    tca_costs = m["tca_slip_bps"] + m["tca_fees_bps"] + m["tca_adv_bps"]
    return 0.5*m["sharpe"] + 0.2*m["return_adj"] + 0.2*max(0.0, m.get("kelly_eff", 0.0)) - 0.1*(tca_costs/10000.0)


def objective(trial: optuna.trial.Trial, args):
    # семплінг простору
    params = {}
    for k, (lo, hi, tp) in SEARCH_SPACE.items():
        if tp is int:
            params[k] = trial.suggest_int(k, lo, hi)
        else:
            params[k] = trial.suggest_float(k, lo, hi)

    base_cfg = yaml.safe_load(open(args.base_profile, "r", encoding="utf-8"))
    cfg = apply_overrides(base_cfg, params)

    with tempfile.TemporaryDirectory() as td:
        m = run_replay(cfg, args.replay_dir, workdir=td)

    # Hard‑фільтри → prune
    if m["cvar95"] < HARD_LIMITS["cvar95_min"]:  # більш негативне — гірше
        raise optuna.TrialPruned("cvar95 breach")
    if m["max_dd"] > HARD_LIMITS["max_dd_max"]:
        raise optuna.TrialPruned("max_dd breach")
    if m["latency_p99"] > HARD_LIMITS["latency_p99_max"]:
        raise optuna.TrialPruned("latency p99 breach")
    if m["deny_rate"] > HARD_LIMITS["deny_rate_max"]:
        raise optuna.TrialPruned("deny‑rate breach")
    if m["ece"] > HARD_LIMITS["ece_max"]:
        raise optuna.TrialPruned("ECE breach")

    val = score(m)

    # Лог
    os.makedirs("artifacts", exist_ok=True)
    with open("artifacts/optuna_trials.jsonl", "a", encoding="utf-8") as f:
        rec = {"params": params, "metrics": m, "score": val, "ts": time.time()}
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    trial.set_user_attr("metrics", m)
    return val


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--replay-dir", required=True)
    p.add_argument("--base-profile", required=True)
    p.add_argument("--n-trials", type=int, default=200)
    p.add_argument("--storage", default="sqlite:///artifacts/optuna.db")
    p.add_argument("--study", default="aurora_shadow_v1")
    p.add_argument("--timeout-min", type=int, default=0)
    args = p.parse_args()

    sampler = TPESampler(seed=42, multivariate=True)
    pruner = MedianPruner(n_startup_trials=20, n_warmup_steps=2)

    study = optuna.create_study(direction="maximize", sampler=sampler, pruner=pruner, storage=args.storage, study_name=args.study, load_if_exists=True)
    study.optimize(lambda t: objective(t, args), n_trials=args.n_trials, timeout=(args.timeout_min*60) if args.timeout_min>0 else None, show_progress_bar=True)

    # Збереження топ‑результатів
    pathlib.Path("profiles").mkdir(exist_ok=True)
    best = study.best_trial
    best_params = best.params

    # Побудувати повний профіль → YAML
    base_cfg = yaml.safe_load(open(args.base_profile, "r", encoding="utf-8"))
    best_cfg = apply_overrides(base_cfg, best_params)

    out_profile = "profiles/aurora_shadow_best.yaml"
    yaml.safe_dump(best_cfg, open(out_profile, "w", encoding="utf-8"), allow_unicode=True)

    # Резюме
    pathlib.Path("reports").mkdir(exist_ok=True)
    with open("reports/optuna_summary.json", "w", encoding="utf-8") as f:
        json.dump({
            "best_value": best.value,
            "best_params": best_params,
            "best_metrics": best.user_attrs.get("metrics", {}),
            "n_trials": len(study.trials),
        }, f, ensure_ascii=False, indent=2)

    with open("reports/optuna_summary.md", "w", encoding="utf-8") as f:
        f.write(f"# Optuna Summary\nBest value: {best.value}\n\nBest params:\n\n")
        for k, v in best_params.items():
            f.write(f"- {k}: {v}\n")

if __name__ == "__main__":
    main()