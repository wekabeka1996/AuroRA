#!/usr/bin/env python3
from __future__ import annotations

"""
Aurora — run_replay
===================

End-to-end replay runner:
  • Loads SSOT-config and schema
  • Replays raw events from JSONL (or synthetic stream) with pacing
  • Computes a minimal inline feature set (microprice delta / order-book imbalance / trade size)
  • Scores via ScoreModel and calibrates probabilities
  • Emits DecisionLog records and triggers XAI alerts

Usage
-----
    python -m scripts.run_replay \
        --input data/events.jsonl \
        --config configs/default.toml \
        --schema configs/schema.json \
        --speed 2.0 \
        --calib isotonic \
        --logdir logs/decisions

Input format
------------
JSONL with 1 raw event per line (dict). Supported keys include any aliases
recognized by Normalizer (ts/T/time, price/p, qty/size, bid/ask, etc.).

Notes
-----
- No external deps; JSON parsing via stdlib.
- Feature extraction here is intentionally lightweight; replace with your
  `core/features/*` modules in production.
"""

import argparse
import json
import math
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Mapping, Optional

from core.config.loader import load_config
from core.ingestion.normalizer import Normalizer
from core.ingestion.replay import Replay
from core.ingestion.sync_clock import ReplayClock
from core.signal.score import ScoreModel
from core.calibration.calibrator import ProbabilityCalibrator
from core.xai.logger import DecisionLogger
from core.xai.schema import validate_decision
from core.xai.alerts import NoTradesAlert, DenySpikeAlert, CalibrationDriftAlert, CvarBreachAlert


# -------------------- IO --------------------

def read_jsonl(path: Path) -> Iterable[Mapping[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def synthetic_stream(n: int = 1000) -> Iterable[Mapping[str, Any]]:
    # Simple synthetic price/quote/trade stream for demo
    ts = 0
    price = 100.0
    for i in range(n):
        ts += 100_000  # 0.1 ms increments (ns)
        # quote
        bid = price - 0.05
        ask = price + 0.05
        yield {"ts": ts, "symbol": "BTCUSDT", "bid": bid, "ask": ask, "bid_size": 1.0 + (i % 3), "ask_size": 1.0 + ((i+1) % 3)}
        # trade
        ts += 50_000
        price += (-1 if (i % 10 == 0) else 1) * 0.01
        yield {"ts": ts, "type": "trade", "symbol": "BTCUSDT", "price": price, "qty": 0.01 * (1 + (i % 5))}


# -------------------- Features --------------------

class InlineFeatures:
    """Minimal inline features for demonstration.

    - microprice delta: ΔMP_t = MP_t - MP_{t-1}
    - order book imbalance (OBI): (ask_sz - bid_sz) / (ask_sz + bid_sz)
    - trade size (for trade events)
    """

    def __init__(self) -> None:
        self._last_mp: Optional[float] = None

    def compute(self, evt: Mapping[str, Any]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        typ = evt.get("type")
        if typ == "quote":
            bid = float(evt["bid_px"])  # normalizer ensures presence
            ask = float(evt["ask_px"])
            bid_sz = 0.0 if evt.get("bid_sz") is None else float(evt["bid_sz"])
            ask_sz = 0.0 if evt.get("ask_sz") is None else float(evt["ask_sz"])
            mp = (ask * bid_sz + bid * ask_sz) / max(1e-12, (bid_sz + ask_sz)) if (bid_sz + ask_sz) > 0 else (bid + ask) / 2
            if self._last_mp is not None:
                out["microprice_delta"] = mp - self._last_mp
            self._last_mp = mp
            denom = (ask_sz + bid_sz)
            out["obi"] = ((ask_sz - bid_sz) / denom) if denom > 0 else 0.0
        elif typ == "trade":
            out["trade_size"] = float(evt.get("size") or 0.0)
        return out


# -------------------- Decisions --------------------

def make_decision(
    *,
    evt: Mapping[str, Any],
    feats: Mapping[str, float],
    model: ScoreModel,
    calibrator: ProbabilityCalibrator,
    threshold: float,
) -> Optional[Dict[str, Any]]:
    # Cross-asset terms are not used in this demo
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
        "config_hash": "",  # filled by logger
        "config_schema_version": None,  # filled by logger
        "model_version": "demo-0.1",
    }
    validate_decision(rec)
    return rec


# -------------------- Main --------------------

def main() -> None:
    ap = argparse.ArgumentParser(description="Aurora replay runner")
    ap.add_argument("--input", type=str, default="", help="JSONL events; empty -> synthetic stream")
    ap.add_argument("--config", type=str, default="configs/default.toml")
    ap.add_argument("--schema", type=str, default="configs/schema.json")
    ap.add_argument("--profile", type=str, default="", help="Apply named profile from config (e.g. local_low)")
    ap.add_argument("--speed", type=float, default=1.0)
    ap.add_argument("--calib", type=str, default="isotonic", choices=["platt", "isotonic"])
    ap.add_argument("--threshold", type=float, default=0.55)
    ap.add_argument("--logdir", type=str, default="logs/decisions")
    args = ap.parse_args()

    # Load SSOT config (convert to mutable dict for profile overlay)
    cfg_obj = load_config(config_path=args.config, schema_path=args.schema, enable_watcher=False)
    cfg = cfg_obj.as_dict()

    # Apply profile overlay if requested
    def _get_nested(d: dict, parts: list):
        cur = d
        for p in parts:
            if not isinstance(cur, dict) or p not in cur:
                return None
            cur = cur[p]
        return cur

    def _set_nested(d: dict, parts: list, value):
        cur = d
        for p in parts[:-1]:
            if p not in cur or not isinstance(cur[p], dict):
                cur[p] = {}
            cur = cur[p]
        cur[parts[-1]] = value

    def _find_best_split_and_set(base: dict, key: str, value):
        """Try to split underscore-style key into nested path that exists in base.
        For key like 'execution_sla_max_latency_ms' try ['execution','sla','max_latency_ms'], etc.
        Return dot-path string that was set."""
        parts = key.split("_")
        # Try prefixes of increasing length for nesting
        for i in range(1, len(parts)):
            prefix = parts[:i]
            last = "_".join(parts[i:])
            # check if nested prefix exists or is plausible
            nested = _get_nested(base, prefix)
            if nested is None:
                continue
            # set at nested[last]
            _set_nested(base, prefix + [last], value)
            return ".".join(prefix + [last])
        # fallback: set at top-level key
        base[key] = value
        return key

    def _recursive_merge(base: dict, overlay: dict, path: str = "") -> list:
        """Merge overlay into base recursively. Return list of changed dot-paths.
        Overlay keys may be nested dicts or underscore-joined flat keys which we attempt to map to nested paths in base."""
        changes = []
        for k, v in overlay.items():
            cur_path = f"{path}.{k}" if path else k
            if isinstance(v, dict):
                # if base has same key as dict, merge recursively
                if isinstance(base.get(k), dict):
                    changes.extend(_recursive_merge(base[k], v, cur_path))
                else:
                    base[k] = v
                    changes.append(cur_path)
            else:
                # try to map flat key to nested path in base
                if k in base and not isinstance(base.get(k), dict):
                    if base.get(k) != v:
                        base[k] = v
                        changes.append(cur_path)
                else:
                    mapped = _find_best_split_and_set(base, k, v)
                    if mapped:
                        changes.append(mapped)
        return changes

    if args.profile:
        profiles = cfg.get("profile") or {}
        prof = profiles.get(args.profile)
        if prof is None:
            print(f"PROFILE: unknown profile {args.profile}")
            raise SystemExit(61)
        # create copy of cfg for diff
        import copy

        before = copy.deepcopy(cfg)
        changed = _recursive_merge(cfg, prof)
        # write a diff file
        logdir = Path("logs")
        logdir.mkdir(parents=True, exist_ok=True)
        out_path = logdir / f"profile_{args.profile}.txt"
        with out_path.open("w", encoding="utf-8") as fh:
            fh.write(f"APPLIED PROFILE: {args.profile}\n")
            fh.write("CHANGED KEYS:\n")
            for p in changed:
                old = before
                for part in p.split('.'):
                    old = old.get(part, None) if isinstance(old, dict) else None
                new = cfg
                for part in p.split('.'):
                    new = new.get(part, None) if isinstance(new, dict) else None
                fh.write(f"- {p}: {old!r} -> {new!r}\n")
        print(f"PROFILE: applied {args.profile} -> {out_path}")

    # Source
    if args.input:
        src = read_jsonl(Path(args.input))
    else:
        src = synthetic_stream(1000)

    # Ingestion
    norm = Normalizer(source_tag="replay", strict=False)
    clock = ReplayClock(speed=max(1e-6, float(args.speed)))
    replay = Replay(source=src, normalizer=norm, clock=clock, strict=False, pace=True)

    # Model & calibration
    # Simple default weights for demo: rely on inline features
    model = ScoreModel(weights={"microprice_delta": 8.0, "obi": -0.5, "trade_size": 0.05}, intercept=0.0)
    calibrator = ProbabilityCalibrator(method=args.calib)
    # Warm-up calibrator with synthetic prior (uninformative)
    calibrator.fit([0.2, 0.8, 0.4, 0.6], [0, 1, 0, 1])

    # XAI
    logger = DecisionLogger(args.logdir, rotate_daily=True, include_signature=True)
    al_no = NoTradesAlert(window_sec=60)
    al_den = DenySpikeAlert(window_sec=60, rate_thresh=0.9)
    al_cal = CalibrationDriftAlert(bins=10, ece_thresh=0.10)
    al_cvar = CvarBreachAlert(window_size=500, alpha=float(cfg.get("risk.cvar.alpha", 0.95)))

    feats = InlineFeatures()

    def on_evt(evt: Dict[str, Any]) -> None:
        f = feats.compute(evt)
        if not f:
            return
        rec = make_decision(evt=evt, feats=f, model=model, calibrator=calibrator, threshold=float(args.threshold))
        if rec is None:
            return
        logger.write(rec)
        # alerts (use p vs. simple synthetic label y=1 if action was enter)
        ts = int(rec["timestamp_ns"])
        action = rec["action"]
        _ = al_no.update(ts, action)
        _ = al_den.update(ts, action)
        y = 1 if action == "enter" else 0
        _ = al_cal.update(ts, rec["p"], y)
        # dummy return: treat enter as small random return around 0
        pseudo_ret = 0.001 if action == "enter" else -0.001
        _ = al_cvar.update(ts, pseudo_ret)

    replay.play(on_event=on_evt)


if __name__ == "__main__":
    main()