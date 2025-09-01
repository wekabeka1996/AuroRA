"""
Execution — Order routing and lifecycle management
=================================================

This module provides production-grade execution components for Aurora's TCA
(trade cost analysis) pipeline:

- **Router**: Maker/taker decision engine with latency economics and SLA gates
- **SLAMonitor**: Rolling latency monitoring and post-latency edge calculation  
- **PartialSlicer**: Idempotent order slicing with geometric decay and fill probability
- **IdempotencyStore**: Thread-safe deduplication for order lifecycle events

Key integrations:
- TCA latency economics (core.tca.latency.SLAGate)
- Cox hazard models for fill probability (core.tca.hazard_cox.CoxPH)
- SSOT configuration (execution.sla.*, execution.router.*)
- XAI decision logging with WHY codes
"""

from .router import Router, Decision
from .sla import SLAMonitor, SLASummary
from .partials import PartialSlicer, SliceDecision
from .idempotency import IdempotencyStore

__all__ = [
    "Router", "Decision",
    "SLAMonitor", "SLASummary", 
    "PartialSlicer", "SliceDecision",
    "IdempotencyStore"
]