"""
Regime — Market regime detection and management
===============================================

This package provides:
- Page-Hinkley change detector for mean shifts
- GLR (Generalized Likelihood Ratio) for structural breaks
- Regime manager with quantile gates and hysteresis
"""

from .glr import GLRMeanShift, GLRResult
from .manager import RegimeManager, RegimeState
from .page_hinkley import PageHinkley, PHResult

__all__ = [
    "PageHinkley",
    "PHResult",
    "GLRMeanShift",
    "GLRResult",
    "RegimeManager",
    "RegimeState",
]
