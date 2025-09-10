"""
Aurora Configuration System
---------------------------

Single Source of Truth (SSOT) configuration management with:
- TOML loading with ENV overrides
- JSON Schema validation with defaults
- Hot-reload with whitelist protection
- Deterministic config hashing
"""

from .loader import Config, ConfigError, ConfigManager, HotReloadViolation, get_config, load_config
from .schema_validator import SchemaLoadError, SchemaValidationError, SchemaValidator

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
