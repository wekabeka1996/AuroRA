"""
Aurora Configuration System
---------------------------

Single Source of Truth (SSOT) configuration management with:
- TOML loading with ENV overrides
- JSON Schema validation with defaults
- Hot-reload with whitelist protection
- Deterministic config hashing
"""

from .loader import ConfigManager, load_config, get_config, Config, ConfigError, HotReloadViolation
from .schema_validator import SchemaValidator, SchemaValidationError, SchemaLoadError

__all__ = [
    "ConfigManager",
    "load_config",
    "get_config",
    "Config",
    "ConfigError",
    "HotReloadViolation",
    "SchemaValidator",
    "SchemaValidationError",
    "SchemaLoadError",
]