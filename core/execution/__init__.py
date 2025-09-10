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

from .idempotency import IdempotencyStore
from .partials import PartialSlicer, SliceDecision
from .router import Decision, Router
from .sla import SLAMonitor, SLASummary

__all__ = [
    "Router", "Decision",
    "SLAMonitor", "SLASummary",
    "PartialSlicer", "SliceDecision",
    "IdempotencyStore"
]
