# Aurora Signal Package
"""
Signal processing modules for Aurora trading system.

This package provides signal generation and analysis components,
including cross-asset dependencies and lead-lag analysis.
"""

from . import leadlag_hy, score

__all__ = ["leadlag_hy", "score"]