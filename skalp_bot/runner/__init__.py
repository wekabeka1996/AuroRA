"""
Runner package for Aurora-integrated scalper.

Exposes module `run_live_aurora` used by tools and tests.
"""

from .run_live_aurora import main, _reset_events_writer, create_adapter
