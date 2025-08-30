"""
Regime — Market regime detection and management
===============================================

This package provides:
- Page-Hinkley change detector for mean shifts
- GLR (Generalized Likelihood Ratio) for structural breaks
- Regime manager with quantile gates and hysteresis
"""

from .page_hinkley import PageHinkley, PHResult
from .glr import GLRMeanShift, GLRResult
from .manager import RegimeManager, RegimeState

__all__ = [
    "PageHinkley",
    "PHResult",
    "GLRMeanShift",
    "GLRResult",
    "RegimeManager",
    "RegimeState",
]