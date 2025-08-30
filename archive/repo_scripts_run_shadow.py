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
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from core.config.loader import load_config
from core.ingestion.normalizer import Normalizer
from core.ingestion.replay import Replay
from core.ingestion.sync_clock import ReplayClock
from core.signal.score import ScoreModel
from core.calibration.calibrator import ProbabilityCalibrator
from core.universe.ranking import UniverseRanker
from core.xai.logger import DecisionLogger
from core.xai.schema import validate_decision
from core.governance.canary import Canary


# --------------- IO ---------------

def read_jsonl_stream(path: Optional[Path], follow: bool) -> Iterable[Mapping[str, Any]]:
    if path is None:
        fh = sys.stdin
        while True:
            line = fh.readline()
            if not line:
                time.sleep(0.05)
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj
    else:
        with path.open("r", encoding="utf-8") as fh:
            while True:
                pos = fh.tell()
                line = fh.readline()
                if not line:
                    if not follow:
                        break
                    time.sleep(0.05)
                    fh.seek(pos)
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    yield obj


# --------------- Minimal features ---------------

class InlineFeatures:
    def __init__(self) -> None:
        self._last_mp: Dict[str, float] = {}

    def compute(self, evt: Mapping[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        typ = evt.get("type")
        sym = evt.get("symbol", "?")
        if typ == "quote":
            bid = float(evt["bid_px"])  # ensured by Normalizer
            ask = float(evt["ask_px"])
            bid_sz = 0.0 if evt.get("bid_sz") is None else float(evt["bid_sz"])
            ask_sz = 0.0 if evt.get("ask_sz") is None else float(evt["ask_sz"])
            mp = (ask * bid_sz + bid * ask_sz) / max(1e-12, (bid_sz + ask_sz)) if (bid_sz + ask_sz) > 0 else (bid + ask) / 2
            if sym in self._last_mp:
                out["microprice_delta"] = mp - self._last_mp[sym]
            self._last_mp[sym] = mp
            denom = (ask_sz + bid_sz)
            out["obi"] = ((ask_sz - bid_sz) / denom) if denom > 0 else 0.0
            out["spread_bps"] = ((ask - bid) / ((ask + bid) / 2)) * 1e4
            out["liq"] = bid_sz + ask_sz
        elif typ == "trade":
            out["trade_size"] = float(evt.get("size") or 0.0)
        return out


# --------------- Decisioning ---------------

def make_decision(evt: Mapping[str, Any], feats: Mapping[str, float], model: ScoreModel, calibrator: ProbabilityCalibrator, threshold: float) -> Dict[str, Any]:
    S = model.score_only(feats)
    p_raw = 1.0 / (1.0 + pow(2.718281828459045, -max(-40.0, min(40.0, S))))
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

    # Universe
    ranker = UniverseRanker()

    # XAI / Governance
    logger = DecisionLogger(args.logdir, rotate_daily=True, include_signature=True)
    canary = Canary()

    feats = InlineFeatures()

    def on_evt(evt: Dict[str, Any]) -> None:
        f = feats.compute(evt)
        if not f:
            return
        # update universe metrics if quote
        if evt.get("type") == "quote":
            symbol = evt["symbol"]
            ranker.update_metrics(
                symbol,
                liquidity=f.get("liq", 0.0),
                spread_bps=f.get("spread_bps", 0.0),
                p_fill=0.6,  # placeholder; plug Cox PH if available
                regime_flag=1.0,  # could wire regime manager output here
            )
            active = ranker.rank(top_k=args.topk)
            # choose only if symbol is active (hysteresis-in)
            if not any(r.symbol == symbol and r.active for r in active):
                return

        # decision
        rec = make_decision(evt, f, model, calibrator, threshold=float(args.threshold))
        logger.write(rec)
        canary.on_decision(ts_ns=rec["timestamp_ns"], action=rec["action"], p=rec["p"])  # y unknown in shadow

    replay.play(on_event=on_evt)


if __name__ == "__main__":
    main()
