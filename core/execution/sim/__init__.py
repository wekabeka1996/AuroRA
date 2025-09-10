"""Simulation adapters and sinks for execution tests."""

from .adapter import SimAdapter
from .local_sink import SimLocalSink

__all__ = ["SimAdapter", "SimLocalSink"]
