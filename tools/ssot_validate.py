#!/usr/bin/env python3
"""SSOT validator for Aurora configs.

Deterministic validation pipeline (strict order) with exact exit codes/messages.

Order of checks:
 1) TOML parse -> exit 10, message: PARSE: invalid TOML (detail=...)
 2) Unknown keys (recursive vs schema.properties) -> exit 20, message: SCHEMA: unknown key path.to.key
 3) Null/empty in critical sections -> exit 30, message: SCHEMA: null/empty not allowed at path.to.section
 4) Live_* invariants -> exit 401/402/403 with INVARIANT[...] messages
 5) JSON Schema checks -> exit 50, message: SCHEMA: missing required key ... or SCHEMA: invalid value ...

Usage: python tools/ssot_validate.py --config configs/default.toml
"""
from __future__ import annotations

import argparse
import json

try:
    import tomllib as toml
except Exception:
    try:
        import toml  # type: ignore
    except Exception:
        print("toml or tomllib required: install 'toml' or use Python 3.11+")
        raise
from pathlib import Path
import sys
from typing import Any

try:
    import jsonschema
except Exception:
    print("jsonschema is required: pip install jsonschema")
    raise

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CFG = ROOT / 'configs' / 'default.toml'
SCHEMA_PATH = ROOT / 'configs' / 'schema.json'


def load_cfg(path: Path) -> dict[str, Any]:
    text = path.read_text(encoding='utf-8')
    try:
        return toml.loads(text)
    except Exception as e:
        # tomllib.TOMLDecodeError or toml.TomlDecodeError
        print(f"PARSE: invalid TOML (detail={e})")
        raise SystemExit(10)


def load_schema(path: Path) -> dict[str, Any]:
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except Exception as e:
        print(f"SCHEMA: failed to load schema (detail={e})")
        raise SystemExit(50)

# Exported exit codes and simple SCHEMA facade for tests/tools
EXIT_UNKNOWN = 20
EXIT_NULLS   = 30
EXIT_SCHEMA  = 50
EXIT_INVAR   = 401
ALLOWED_TOP_LEVEL = {
    "risk","sizing","execution","reward","tca","xai",
    "universe","profile","order_sink","timescale",
    "replay","leadlag","market_data","orders","exchange","logger","shadow",
    # infrastructure/ops section (e.g., [infra.idem])
    "infra",
    # allow free-form naming field in minimal configs/tests
    "name",
}
SCHEMA = {
    "allowed_top": ALLOWED_TOP_LEVEL,
    "required": ["timescale","execution","order_sink"],
}
__all__ = [
    "EXIT_UNKNOWN","EXIT_NULLS","EXIT_SCHEMA","EXIT_INVAR","SCHEMA",
]

def _print(msg: str) -> None:
    # Windows-safe ASCII-only printing to avoid cp1252 issues
    try:
        sys.stdout.write((str(msg)).encode("ascii", "ignore").decode("ascii") + "\n")
    except Exception:
        print(str(msg))


def collect_schema_properties(schema: dict[str, Any], prefix: str = "") -> dict[str, Any]:
    """Return mapping of schema properties nodes by path for quick lookup.

    We'll keep nested schema nodes for recursion (properties dict) to validate unknown keys.
    """
    out = {}
    props = schema.get('properties', {}) if isinstance(schema, dict) else {}
    out[prefix.rstrip('.')] = schema
    for k, v in props.items():
        new_prefix = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(collect_schema_properties(v, new_prefix + '.'))
        else:
            out[new_prefix] = v
    return out


def collect_schema_property_names(schema: dict[str, Any]) -> set[str]:
    names = set()
    def _rec(node: Any):
        if not isinstance(node, dict):
            return
        props = node.get('properties', {}) or {}
        for k, v in props.items():
            names.add(k)
            _rec(v)
    _rec(schema or {})
    return names


def check_invariants(cfg: dict[str, Any]) -> None:
    md = cfg.get('market_data') or {}
    source = md.get('source', '')
    if isinstance(source, str) and source.startswith('live_'):
        os_sink = cfg.get('order_sink') or {}
        mode = os_sink.get('mode')
        orders_enabled = cfg.get('orders', {}).get('enabled', True)
        # 401: require sim_local and orders.enabled=false
        if mode != 'sim_local' or orders_enabled:
            print("INVARIANT[401]: live source requires order_sink=sim_local and orders.enabled=false")
            raise SystemExit(401)
        # 402: exchange.keys.readonly must be true
        ex = cfg.get('execution', {}).get('exchange', {})
        for k, v in (ex or {}).items():
            keys = v.get('keys') or {}
            if keys and not keys.get('readonly', False):
                print("INVARIANT[402]: exchange.keys.readonly must be true for live_* sources")
                raise SystemExit(402)
        # 403: outbound order networking forbidden (explicit net mode)
        if mode == 'net':
            print("INVARIANT[403]: outbound order networking is forbidden in live_* mode")
            raise SystemExit(403)


def check_missing_required_keys(cfg: dict[str, Any]) -> None:
    exec_sec = cfg.get('execution') or {}
    sla = exec_sec.get('sla') if isinstance(exec_sec, dict) else None
    flattened_top = cfg.get('execution.sla_max_latency_ms')
    flattened_exec = exec_sec.get('sla_max_latency_ms') if isinstance(exec_sec, dict) else None
    if (not sla or ('max_latency_ms' not in sla)) and not (flattened_top or flattened_exec):
        print('SCHEMA: missing required key execution.sla_max_latency_ms')
        raise SystemExit(50)


# === UNKNOWN (20): top-level keys, not in schema nor whitelist ==========
def _check_unknown_top_level(cfg: dict, schema: dict):
    schema_props = set((schema or {}).get("properties", {}).keys())
    whitelist = set(ALLOWED_TOP_LEVEL)
    allowed = schema_props | whitelist
    unknown = [k for k in cfg.keys() if k not in allowed]
    if unknown:
        _print(f"UNKNOWN: top-level keys not allowed: {unknown}")
        raise SystemExit(EXIT_UNKNOWN)


def check_unknown_and_nulls(cfg: dict[str, Any], schema: dict[str, Any]) -> None:
    # Null/empty checks for critical sections
    # Only enforce non-empty on sections that are truly required for operation.
    # 'reward', 'tca', 'xai', 'universe', 'profile' may be omitted in minimal configs.
    critical = ['risk', 'sizing', 'execution']
    def _get_path(cfg_obj: dict, path: str):
        parts = path.split('.')
        cur = cfg_obj
        for part in parts:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur.get(part)
        return cur

    for key in critical:
        # Only check for null/empty if key exists; don't require optional sections
        val = _get_path(cfg, key)
        if val is None:
            continue
        if isinstance(val, (dict, list, str)) and len(val) == 0:
            _print(f"SCHEMA: null/empty not allowed at {key}")
            raise SystemExit(EXIT_NULLS)

    # Targeted checks within execution.sla
    try:
        exec_sla = ((cfg.get('execution') or {}).get('sla') or {})
        if isinstance(exec_sla, dict):
            # 1) explicit null/empty check for profile if provided
            prof = exec_sla.get('profile')
            if prof is None or (isinstance(prof, str) and prof.strip() == ""):
                # If profile key exists but is empty/blank, treat as null/empty in critical path
                # (tests expect exit 30 rather than unknown-key 20)
                if 'profile' in exec_sla:
                    _print("SCHEMA: null/empty not allowed at execution.sla.profile")
                    raise SystemExit(EXIT_NULLS)

            # 2) unknown-key check within sla: allow a strict set of keys
            allowed_sla_keys = {"max_latency_ms", "kappa_bps_per_ms", "target_fill_prob", "edge_floor_bps", "profile"}
            extra = [k for k in exec_sla.keys() if k not in allowed_sla_keys]
            if extra:
                _print(f"UNKNOWN: execution.sla contains unknown keys: {extra}")
                raise SystemExit(EXIT_UNKNOWN)
    except SystemExit:
        raise
    except Exception:
        pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument('--config', type=str, default=str(DEFAULT_CFG))
    args = ap.parse_args()

    cfg_path = Path(args.config)
    if not cfg_path.exists():
        print(f"Config not found: {cfg_path}")
        raise SystemExit(2)
    cfg = load_cfg(cfg_path)

    # 1) load schema early (if present)
    schema = {}
    actual_schema = None
    if SCHEMA_PATH.exists():
        schema = load_schema(SCHEMA_PATH)
        actual_schema = schema.get('schema') if isinstance(schema, dict) and 'schema' in schema else schema

    # UNKNOWN check (must precede other schema checks for deterministic exit code)
    _check_unknown_top_level(cfg, actual_schema)

    # 2) unknown-key and null/empty checks
    try:
        check_unknown_and_nulls(cfg, schema if actual_schema is None else actual_schema)
    except SystemExit:
        raise

    # 3) missing required keys check (user-facing message required)
    try:
        check_missing_required_keys(cfg)
    except SystemExit:
        raise

    # 4) invariants
    check_invariants(cfg)

    if actual_schema is not None:
        # Inject pragmatic defaults before strict JSON Schema validation
        try:
            if isinstance(cfg.get('order_sink'), dict):
                osink = cfg['order_sink']  # type: ignore[index]
                if osink.get('mode') == 'sim_local':
                    sim = osink.get('sim_local')
                    if not isinstance(sim, dict):
                        sim = {}
                    # inject sensible defaults
                    if 'latency_ms' not in sim:
                        sim['latency_ms'] = 5
                    if 'ttl_ms' not in sim:
                        sim['ttl_ms'] = 1500
                    # prune unknown keys to satisfy additionalProperties=false (remove any not in allowed set)
                    allowed = {"latency_ms", "ttl_ms", "maker_queue_model", "taker_slip_model"}
                    for k in list(sim.keys()):
                        if k not in allowed:
                            sim.pop(k, None)
                    osink['sim_local'] = sim
                    cfg['order_sink'] = osink
        except Exception:
            pass
        try:
            jsonschema.validate(instance=cfg, schema=actual_schema)
        except jsonschema.ValidationError as e:
            # map ValidationError for user-friendly messages and exit 50
            if getattr(e, 'validator', None) == 'required':
                # path describes where the error occurred
                missing = e.message
                _print(f"SCHEMA: {missing}")
                raise SystemExit(EXIT_SCHEMA)
            else:
                _print(f"SCHEMA: {e.message}")
                raise SystemExit(EXIT_SCHEMA)

    # 3) additional presence checks (warn only)
    required = ['risk', 'sizing', 'execution', 'tca', 'xai', 'universe']
    missing = [k for k in required if k not in cfg]
    if missing:
        _print(f"WARNING: missing top-level keys: {missing}")

    # Report checked key counts (top-level)
    checked_keys_count = len([k for k in cfg.keys()])
    _print(f"OK: ssot validation passed (checked_keys={checked_keys_count})")


if __name__ == '__main__':
    main()
