#!/usr/bin/env python3
from __future__ import annotations

"""
Aurora — run_shadow
===================

Shadow runner that mirrors live decisioning without placing orders.
It ingests a stream of events (stdin or JSONL file with optional --follow),
computes features → score → calibrated probability, filters/ranks the universe,
and produces DecisionLog entries plus governance canary alerts. No execution.

Usage
-----
    # From a JSONL file (follow tail)
    python -m scripts.run_shadow --input data/live_feed.jsonl --follow \
        --config configs/default.toml --schema configs/schema.json \
        --calib isotonic --logdir logs/shadow

    # From stdin
    tail -f data/live_feed.jsonl | python -m scripts.run_shadow --stdin

Notes
-----
- This is a production-style scaffold; replace InlineFeatures with core/features/*.
- Router is not called in shadow (no order placement); we still compute
  p, score, rank and XAI/alerts.
"""
import argparse
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from core.config.loader import load_config
from core.ingestion.normalizer import Normalizer
from core.ingestion.replay import Replay
from core.ingestion.sync_clock import ReplayClock
from core.signal.score import ScoreModel
from core.calibration.calibrator import ProbabilityCalibrator
from repo.core.universe.ranking import UniverseRanker
from core.xai.logger import DecisionLogger
from core.xai.schema import validate_decision
from core.governance.canary import Canary
from core.tca.hazard_cox import CoxPH
from core.regime.manager import RegimeManager, RegimeState


# --------------- IO ---------------

def read_jsonl_stream(path: Optional[Path], follow: bool) -> Iterable[Mapping[str, Any]]:
    if path is None:
        import sys
        import json
        for line in sys.stdin:
            if line.strip():
                yield json.loads(line.strip())
    else:
        import json
        import time
        with open(path, 'r', encoding='utf-8') as f:
            if follow:
                # Simple follow implementation
                while True:
                    line = f.readline()
                    if line:
                        if line.strip():
                            yield json.loads(line.strip())
                    else:
                        time.sleep(0.1)
            else:
                for line in f:
                    if line.strip():
                        yield json.loads(line.strip())


# --------------- Minimal features ---------------

class InlineFeatures:
    def __init__(self) -> None:
        pass

    def compute(self, evt: Mapping[str, Any]) -> Dict[str, float]:
        # Placeholder features - replace with real feature computation
        return {
            "microprice_delta": float(evt.get("microprice_delta", 0.0)),
            "obi": float(evt.get("obi", 0.5)),
            "trade_size": float(evt.get("trade_size", 1000.0)),
        }


# --------------- Decisioning ---------------

def make_decision(evt: Mapping[str, Any], feats: Mapping[str, float], model: ScoreModel, calibrator: ProbabilityCalibrator, threshold: float) -> Dict[str, Any]:
    S = model.score_only(feats)
    p_raw = 1.0 / (1.0 + math.exp(-max(-40.0, min(40.0, S))))
    p = calibrator.calibrate_prob(p_raw)
    action = "enter" if p >= threshold else "deny"
    rec = {
        "decision_id": f"{evt['symbol']}-{evt['ts_ns']}",
        "timestamp_ns": evt["ts_ns"],
        "symbol": evt["symbol"],
        "action": action,
        "score": float(S),
        "p_raw": float(p_raw),
        "p": float(p),
        "threshold": float(threshold),
        "features": dict(feats),
        "components": model.score_event(features=feats).components,
        "config_hash": "",
        "config_schema_version": None,
        "model_version": "shadow-0.1",
    }
    validate_decision(rec)
    return rec


# --------------- Main ---------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Aurora shadow runner")
    ap.add_argument("--input", type=str, default="", help="JSONL feed; empty for stdin if --stdin set")
    ap.add_argument("--follow", action="store_true", help="tail -f the input file")
    ap.add_argument("--stdin", action="store_true", help="read from stdin")
    ap.add_argument("--config", type=str, default="configs/default.toml")
    ap.add_argument("--schema", type=str, default="configs/schema.json")
    ap.add_argument("--calib", type=str, default="isotonic", choices=["platt", "isotonic"])
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--logdir", type=str, default="logs/shadow")
    ap.add_argument("--topk", type=int, default=16, help="rank top-K symbols to be considered active")
    args = ap.parse_args()

    # Config
    cfg = load_config(config_path=args.config, schema_path=args.schema, enable_watcher=False)

    # Source (stdin or file stream)
    path = None if args.stdin or not args.input else Path(args.input)
    src = read_jsonl_stream(path, follow=args.follow)

    # Ingestion
    norm = Normalizer(source_tag="shadow", strict=False)
    # Shadow pacing: run as fast as events arrive; no artificial sleeps here
    clock = ReplayClock(speed=1.0)
    replay = Replay(source=src, normalizer=norm, clock=clock, strict=False, pace=False)

    # Model & calibration
    model = ScoreModel(weights={"microprice_delta": 6.0, "obi": -0.4, "trade_size": 0.03}, intercept=0.0)
    calibrator = ProbabilityCalibrator(method=args.calib)
    calibrator.fit([0.2, 0.8, 0.4, 0.6], [0, 1, 0, 1])

    # CoxPH for fill probability (with sample data for demo)
    coxph = CoxPH(l2=1e-4, max_iter=100)
    sample_data = [
        {'t': 5.0, 'd': 1, 'z': {'microprice_delta': 0.01, 'obi': 0.6, 'trade_size': 1000}},
        {'t': 15.0, 'd': 0, 'z': {'microprice_delta': -0.02, 'obi': 0.3, 'trade_size': 500}},
        {'t': 8.0, 'd': 1, 'z': {'microprice_delta': 0.005, 'obi': 0.8, 'trade_size': 2000}},
        {'t': 25.0, 'd': 0, 'z': {'microprice_delta': 0.03, 'obi': 0.2, 'trade_size': 300}},
    ]
    coxph.fit(sample_data)

    # Regime manager
    regime_mgr = RegimeManager()

    # Universe
    ranker = UniverseRanker()

    # XAI / Governance
    logger = DecisionLogger(logdir=args.logdir)
    canary = Canary()

    # Main loop
    for evt in replay.stream():
        # Features
        feats = InlineFeatures().compute(evt)

        # Decision
        decision = make_decision(evt, feats, model, calibrator, args.threshold)

        # Universe ranking (with real CoxPH p_fill and regime manager)
        # Get horizon from config (default to 10000ms if not set)
        horizon_ms = cfg.get("router.horizon_ms", 10000.0)
        
        # Compute real p_fill using CoxPH
        p_fill = coxph.p_fill(horizon_ms, feats)
        
        # Update regime manager with return data (use microprice_delta as proxy)
        regime_state = regime_mgr.update(feats.get("microprice_delta", 0.0))
        regime_flag = 1.0 if regime_state.regime == "trend" else 0.0
        
        ranker.update_metrics(
            symbol=evt["symbol"],
            liquidity=float(evt.get("liquidity", 1000000.0)),
            spread_bps=float(evt.get("spread_bps", 5.0)),
            p_fill=p_fill,
            regime_flag=regime_flag
        )

        # Log decision
        logger.write(decision)

        # Canary alerts
        canary.on_decision(
            ts_ns=evt["ts_ns"],
            action=decision["action"],
            p=decision["p"],
            y=1 if decision["action"] == "enter" else 0
        )

        # Poll alerts
        alerts = canary.poll()
        for alert in alerts:
            print(f"ALERT: {alert.message}")

        # Rank universe
        ranked = ranker.rank(top_k=args.topk)
        active_symbols = [r.symbol for r in ranked if r.active]

        print(f"Processed {evt['symbol']} | Action: {decision['action']} | P: {decision['p']:.3f} | Active: {len(active_symbols)}")


if __name__ == "__main__":
    main()