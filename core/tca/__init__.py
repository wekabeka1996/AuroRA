"""
TCA — Transaction Cost Analysis
===============================

Modules for modeling and estimating transaction costs in high-frequency trading:

- latency: SLA gates and latency-based edge adjustments
- hazard_cox: Cox proportional hazards for fill probability modeling
- hawkes: Hawkes process for adverse selection and clustering analysis

These modules provide the mathematical foundations for Aurora's execution
optimization and risk management systems.
"""

from . import latency, hazard_cox, hawkes

__all__ = ["latency", "hazard_cox", "hawkes"]