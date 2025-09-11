"""Aurora top-level package.

Provides governance and health guard primitives used by the API service and core pipeline.
Presence of this file fixes static analysis (Pylance) missing-import warnings for
`from aurora.health import HealthGuard` and `from aurora.governance import Governance`.
"""

from .governance import Governance  # noqa: F401
from .health import HealthGuard  # noqa: F401

__all__ = ["HealthGuard", "Governance"]
