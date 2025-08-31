"""
XAI — Decision logging and alerting primitives
==============================================

This package provides:
- DecisionLog schema and validation
- Thread-safe JSONL logging with tamper-evidence
- Operational alerts for live runs (historical shadow mode removed)
"""

from .schema import SCHEMA_ID, validate_decision, canonical_json
from .logger import DecisionLogger
from .alerts import (
    AlertResult,
    NoTradesAlert,
    DenySpikeAlert,
    CalibrationDriftAlert,
    CvarBreachAlert,
)

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