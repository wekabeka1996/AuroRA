from __future__ import annotations

"""
XAI — DecisionLog schema and validation helpers
==============================================

Defines a minimal, versioned schema for decision logs, plus validation and
canonical JSON utilities for stable hashing and storage.

Record layout (all keys snake_case):
{
  "decision_id": str,                 # unique id (uuid4 suggested by caller)
  "timestamp_ns": int,                # wall-clock ns when decision emitted
  "symbol": str,                      # instrument symbol
  "action": str,                      # e.g., 'enter', 'exit', 'hold', 'deny'
  "score": float,                     # raw score S(t)
  "p_raw": float,                     # sigmoid(score)
  "p": float,                         # calibrated probability
  "threshold": float,                 # entry threshold p*(c') after TCA
  "features": {str: float},           # subset or summary of features used
  "components": {str: float},         # score decomposition (lin, intercept, cross, gamma, ...)
  "config_hash": str,                 # sha256 of canonical SSOT-config
  "config_schema_version": str|null,  # schema id/version for traceability
  "model_version": str,               # semantic version of model/weights
  # Optional extensions for full integration:
  "why_code": str,                    # reason code for deny/allow
  "gate_ok": bool,                    # result of gate matrix
  "edge_breakdown": dict,             # TCA: c_maker/taker, κ, L, p*, E[Π]
  "alpha_spent": float,               # governance alpha spent
  "policy_id": str,                   # governance policy ID
  "lambdas": dict,                    # λ_cal, λ_reg, λ_liq, λ_dd, λ_lat
  "regime": str,                      # current market regime
}

This schema purposefully avoids external deps and enforces only type/required checks.
"""

import json
from typing import Any, Dict, Mapping, Optional

SCHEMA_ID = "aurora.decisionlog/v1"

REQUIRED_KEYS = {
    "decision_id": str,
    "timestamp_ns": int,
    "symbol": str,
    "action": str,
    "score": (int, float),
    "p_raw": (int, float),
    "p": (int, float),
    "threshold": (int, float),
    "features": dict,
    "components": dict,
    "config_hash": str,
    "model_version": str,
}

OPTIONAL_KEYS = {
    "config_schema_version": (str, type(None)),
    # Extended optional keys for full Aurora integration
    "why_code": str,
    "gate_ok": bool,
    "edge_breakdown": dict,
    "alpha_spent": (int, float),
    "policy_id": str,
    "lambdas": dict,
    "regime": str,
}


def validate_decision(rec: Mapping[str, Any]) -> None:
    if not isinstance(rec, Mapping):
        raise TypeError("decision record must be a mapping")
    for k, typ in REQUIRED_KEYS.items():
        if k not in rec:
            raise ValueError(f"missing required field: {k}")
        if not isinstance(rec[k], typ):
            raise TypeError(f"field '{k}' must be {typ} (got {type(rec[k])})")
    for k, typ in OPTIONAL_KEYS.items():
        if k in rec and not isinstance(rec[k], typ):
            raise TypeError(f"field '{k}' must be {typ} (got {type(rec[k])})")
    # extra sanity ranges
    for prob_key in ("p_raw", "p", "threshold"):
        v = float(rec[prob_key])
        if not (0.0 <= v <= 1.0):
            raise ValueError(f"field '{prob_key}' must be in [0,1]")
    if int(rec["timestamp_ns"]) < 0:
        raise ValueError("timestamp_ns must be non-negative")


def canonical_json(obj: Mapping[str, Any]) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def schema_id() -> str:
    return SCHEMA_ID
