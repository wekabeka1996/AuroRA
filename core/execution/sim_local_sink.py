import warnings

warnings.warn(
    "core.execution.sim_local_sink is deprecated; use core.execution.sim.local_sink.SimLocalSink",
    DeprecationWarning,
    stacklevel=2,
)

from core.execution.sim.local_sink import SimLocalSink  # re-export

__all__ = ["SimLocalSink"]
