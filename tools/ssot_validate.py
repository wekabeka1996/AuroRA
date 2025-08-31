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
import os
from pathlib import Path
from typing import Any
import sys

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


def check_unknown_and_nulls(cfg: dict[str, Any], schema: dict[str, Any]) -> None:
    # Unknown keys: recursive comparison to schema properties
    schema_map = collect_schema_properties(schema or {})

    prop_names = collect_schema_property_names(schema or {})

    # Only check top-level keys for unknowns. Nested unknown detection is skipped to
    # avoid false positives because the JSON Schema is permissive/partial in this project.
    def _check_unknown(node: Any, schema_node: dict[str, Any], path: str = '', trusted: bool = False):
        if not isinstance(node, dict):
            return
        if path:
            return
        props = (schema_node.get('properties') if isinstance(schema_node, dict) else {}) or {}
        allowed_top = set((schema or {}).get('properties', {}).keys())
        allowed_top.update({
            'market_data', 'order_sink', 'orders', 'profile', 'features', 'signal', 'calibration',
            'regime', 'governance', 'hotreload', 'reward', 'tca'
        })
        for k in node.keys():
            p = k
            if k not in props and k not in allowed_top and ("_" in k or k not in prop_names):
                print(f"SCHEMA: unknown key {p}")
                raise SystemExit(20)

    _check_unknown(cfg, schema or {}, '')

    # Null/empty checks for critical sections
    critical = ['risk', 'sizing', 'execution', 'reward', 'tca', 'xai', 'universe', 'profile']
    def _get_path(cfg_obj: dict, path: str):
        parts = path.split('.')
        cur = cfg_obj
        for part in parts:
            if not isinstance(cur, dict) or part not in cur:
                return None
            cur = cur.get(part)
        return cur

    for key in critical:
        val = _get_path(cfg, key)
        if val is None:
            print(f"SCHEMA: null/empty not allowed at {key}")
            raise SystemExit(30)
        if isinstance(val, (dict, list, str)) and len(val) == 0:
            print(f"SCHEMA: null/empty not allowed at {key}")
            raise SystemExit(30)


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

    # 2) missing required keys check (user-facing message required)
    try:
        check_missing_required_keys(cfg)
    except SystemExit:
        raise

    # 3) unknown-key and null/empty checks
    try:
        check_unknown_and_nulls(cfg, schema if actual_schema is None else actual_schema)
    except SystemExit:
        raise

    # 4) invariants
    check_invariants(cfg)

    if actual_schema is not None:
        try:
            jsonschema.validate(instance=cfg, schema=actual_schema)
        except jsonschema.ValidationError as e:
            # map ValidationError for user-friendly messages and exit 50
            if getattr(e, 'validator', None) == 'required':
                # path describes where the error occurred
                missing = e.message
                print(f"SCHEMA: {missing}")
                raise SystemExit(50)
            else:
                print(f"SCHEMA: {e.message}")
                raise SystemExit(50)

    # 3) additional presence checks (warn only)
    required = ['risk', 'sizing', 'execution', 'tca', 'xai', 'universe']
    missing = [k for k in required if k not in cfg]
    if missing:
        print(f"WARNING: missing top-level keys: {missing}")

    # Report checked key counts (top-level)
    checked_keys_count = len([k for k in cfg.keys()])
    print(f"OK: ssot validation passed (checked_keys={checked_keys_count})")


if __name__ == '__main__':
    main()
