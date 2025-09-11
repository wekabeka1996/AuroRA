"""API package for Aurora FastAPI service.

Exposes pydantic request/response models via `api.models` for import safety.
Presence of this file resolves Pylance missing-import warnings for `api.models`.
"""

from . import models  # noqa: F401

__all__ = ["models"]
