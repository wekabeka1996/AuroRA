import warnings

warnings.warn(
    "core.execution.sim_adapter is deprecated; use core.execution.sim.adapter.SimAdapter",
    DeprecationWarning,
    stacklevel=2,
)

from core.execution.sim.adapter import SimAdapter  # re-export

__all__ = ["SimAdapter"]
