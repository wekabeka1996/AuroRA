#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from hashlib import sha256
from pathlib import Path
from typing import Any, Dict

import sys
from pathlib import Path as _P
# Ensure repository root is on sys.path so `core` package imports work when run from tools/
ROOT = str(_P(__file__).resolve().parents[1])
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from core.config.loader import load_config


def _sha256_text(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()


def merge_profile_to_dict(cfg: Dict[str, Any], profile: Dict[str, Any]) -> Dict[str, Any]:
    # simple deep-merge: profile overrides
    out = json.loads(json.dumps(cfg))
    def _rec(o, p):
        for k, v in p.items():
            if isinstance(v, dict) and isinstance(o.get(k), dict):
                _rec(o[k], v)
            else:
                # If base has a dict and overlay is scalar (shorthand), keep object shape
                if isinstance(o.get(k), dict) and not isinstance(v, dict):
                    # place shorthand under a 'profile' key to preserve object
                    o[k]['profile'] = v
                else:
                    o[k] = v
    _rec(out, profile)
    return out


def normalize_profile_flat_keys(profile: Dict[str, Any]) -> Dict[str, Any]:
    """Convert known flat underscore keys into nested structure expected by config schema."""
    mapping = {
        "execution_sla_max_latency_ms": ("execution", "sla", "max_latency_ms"),
        "replay_chunk_minutes": ("replay", "chunk_minutes"),
        "sizing_max_position_usd": ("sizing", "max_position_usd"),
        "sizing_leverage": ("sizing", "leverage"),
        "universe_top_n": ("universe", "top_n"),
        "universe_spread_bps_limit": ("universe", "spread_bps_limit"),
        "xai_sample_every": ("xai", "sample_every"),
        "xai_level": ("xai", "level"),
        "xai_sig": ("xai", "sig"),
        "leadlag_enable": ("leadlag", "enable"),
        "leadlag_lag_grid": ("leadlag", "lag_grid"),
    }
    out = {}
    for k, v in profile.items():
        if k in mapping:
            parts = mapping[k]
            cur = out
            for p in parts[:-1]:
                cur = cur.setdefault(p, {})
            cur[parts[-1]] = v
        else:
            out[k] = v
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", required=True)
    ap.add_argument("--config", default="configs/default.toml")
    ap.add_argument("--schema", default="configs/schema.json")
    args = ap.parse_args()

    cfg_obj = load_config(config_path=args.config, schema_path=args.schema, enable_watcher=False)
    base = cfg_obj.as_dict()
    profiles = base.get("profile", {})
    prof = profiles.get(args.profile)
    if prof is None:
        print(f"PROFILE: unknown profile {args.profile}")
        raise SystemExit(61)

    prof_norm = normalize_profile_flat_keys(prof)
    eff = merge_profile_to_dict(base, prof_norm)
    # ensure sim_local latency default present when mode==sim_local
    try:
        if (eff.get("order_sink", {}) or {}).get("mode") == "sim_local":
            sim = eff.setdefault("order_sink", {}).setdefault("sim_local", {})
            sim.setdefault("latency_ms", 5)
            sim.setdefault("ttl_ms", 1500)
    except Exception:
        pass
    out_dir = Path("reports")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"effective_{args.profile}.toml"
    # write as TOML using a minimal serializer (avoid external deps)
    def dump_toml(d: Dict[str, Any], fh, prefix: str = ""):
        # writes top-level simple keys and nested tables
        simple = {k: v for k, v in d.items() if not isinstance(v, dict)}
        nested = {k: v for k, v in d.items() if isinstance(v, dict)}
        for k, v in simple.items():
            if isinstance(v, str):
                fh.write(f"{k} = \"{v}\"\n")
            elif isinstance(v, bool):
                fh.write(f"{k} = {str(v).lower()}\n")
            elif isinstance(v, (int, float)):
                fh.write(f"{k} = {v}\n")
            elif isinstance(v, list):
                fh.write(f"{k} = {v}\n")
            else:
                fh.write(f"{k} = \"{str(v)}\"\n")
        for nk, nv in nested.items():
            fh.write("\n")
            table = f"{prefix}{nk}" if prefix == "" else f"{prefix}.{nk}"
            fh.write(f"[{table}]\n")
            dump_toml(nv, fh, prefix=table)

    with out_path.open("w", encoding="utf-8") as fh:
        dump_toml(eff, fh, prefix="")

    txt = out_path.read_text(encoding="utf-8")
    h = _sha256_text(txt)
    print(f"WROTE {out_path} SHA256:{h}")


if __name__ == "__main__":
    main()
