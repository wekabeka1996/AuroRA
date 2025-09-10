"""
XAI — Decision logging and alerting primitives
==============================================

This package provides:
- DecisionLog schema and validation
- Thread-safe JSONL logging with tamper-evidence
- Operational alerts for live runs (historical shadow mode removed)
"""

from .alerts import (
    AlertResult,
    CalibrationDriftAlert,
    CvarBreachAlert,
    DenySpikeAlert,
    NoTradesAlert,
)
from .logger import DecisionLogger
from .schema import SCHEMA_ID, canonical_json, validate_decision

__all__ = [
    "SCHEMA_ID",
    "validate_decision",
    "canonical_json",
    "DecisionLogger",
    "AlertResult",
    "NoTradesAlert",
    "DenySpikeAlert",
    "CalibrationDriftAlert",
    "CvarBreachAlert",
]
