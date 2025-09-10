# repo/core/config/loader.py
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, MutableMapping, Optional, Set, Tuple, Union

try:  # Python 3.11+
    import tomllib  # type: ignore
    _TOML_LOAD = lambda b: tomllib.loads(b.decode("utf-8")) if isinstance(b, (bytes, bytearray)) else tomllib.loads(b)
except Exception:  # pragma: no cover
    # Fallback: requires 'tomli' in environment; we purposely avoid runtime import errors in tests.
    import tomli as _tomli  # type: ignore
    _TOML_LOAD = lambda b: _tomli.loads(b.decode("utf-8")) if isinstance(b, (bytes, bytearray)) else _tomli.loads(b)

logger = logging.getLogger("aurora.config")
logger.setLevel(logging.INFO)

# -------------------- Exceptions --------------------

class ConfigError(Exception):
    """Generic configuration error."""

class SchemaValidationError(ConfigError):
    """Raised when config fails schema validation."""

class HotReloadViolation(ConfigError):
    """Raised when a reload attempts to change non-whitelisted keys."""

# -------------------- Helpers --------------------

def _deep_merge(base: MutableMapping[str, Any], override: Mapping[str, Any]) -> MutableMapping[str, Any]:
    for k, v in override.items():
        if isinstance(v, Mapping) and isinstance(base.get(k), Mapping):
            _deep_merge(base[k], v)  # type: ignore
        else:
            base[k] = v  # type: ignore
    return base

def _parse_env_overrides(prefix: str, env: Mapping[str, str]) -> Dict[str, Any]:
    """
    Parse environment variables of the form:
      PREFIX__SECTION__SUB__KEY = value
    Types: bool/int/float/json/str (in this order of detection).
    """
    out: Dict[str, Any] = {}
    plen = len(prefix) + 2  # account for '__'
    for key, raw in env.items():
        if not key.startswith(prefix + "__"):
            continue
        path = key[plen:].lower().split("__")  # e.g., ['risk', 'cvar', 'limit']
        # type coercion
        val: Any
        txt = raw.strip()
        low = txt.lower()
        if low in ("true", "false"):
            val = (low == "true")
        else:
            try:
                if txt.startswith("{") or txt.startswith("["):
                    val = json.loads(txt)
                elif "." in txt:
                    val = float(txt)
                else:
                    val = int(txt)
            except Exception:
                val = txt  # fallback to string
        # nest
        cur = out
        for p in path[:-1]:
            cur = cur.setdefault(p, {})
        cur[path[-1]] = val
    return out

def _canonical_json(data: Mapping[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, separators=(",", ":"))

def _sha256(text: str) -> str:
    return sha256(text.encode("utf-8")).hexdigest()

def _flatten(d: Mapping[str, Any], prefix: str = "") -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, Mapping):
            out.update(_flatten(v, key))
        else:
            out[key] = v
    return out

def _diff_keys(old: Mapping[str, Any], new: Mapping[str, Any]) -> Set[str]:
    a = _flatten(old)
    b = _flatten(new)
    changed: Set[str] = set()
    keys = set(a.keys()).union(b.keys())
    for k in keys:
        if a.get(k) != b.get(k):
            changed.add(k)
    return changed

# -------------------- Schema-lite validator --------------------

def _validate_schema(data: Any, schema: Mapping[str, Any], path: str = "") -> None:
    """
    Minimal JSON Schema validator (subset):
      - type, properties, required, enum, minimum, maximum, items (object/array recursion)
    """
    def fail(msg: str) -> None:
        raise SchemaValidationError(f"Schema validation failed at '{path or '$'}': {msg}")

    if "type" in schema:
        typ = schema["type"]
        if typ == "object":
            if not isinstance(data, Mapping):
                fail(f"expected object, got {type(data).__name__}")
            props = schema.get("properties", {})
            req = schema.get("required", [])
            for r in req:
                if r not in data:
                    fail(f"missing required key '{r}'")
            for k, v in data.items():
                subschema = props.get(k)
                if subschema is not None:
                    _validate_schema(v, subschema, path=f"{path}.{k}" if path else k)
        elif typ == "array":
            if not isinstance(data, list):
                fail(f"expected array, got {type(data).__name__}")
            item_schema = schema.get("items", {})
            for i, item in enumerate(data):
                _validate_schema(item, item_schema, path=f"{path}[{i}]")
        elif typ == "string":
            if not isinstance(data, str):
                fail("expected string")
            enum = schema.get("enum")
            if enum is not None and data not in enum:
                fail(f"value '{data}' not in enum {enum}")
        elif typ == "number":
            if not isinstance(data, (int, float)):
                fail("expected number")
            if "minimum" in schema and data < schema["minimum"]:
                fail(f"value {data} < minimum {schema['minimum']}")
            if "maximum" in schema and data > schema["maximum"]:
                fail(f"value {data} > maximum {schema['maximum']}")
        elif typ == "integer":
            if not isinstance(data, int):
                fail("expected integer")
            if "minimum" in schema and data < schema["minimum"]:
                fail(f"value {data} < minimum {schema['minimum']}")
            if "maximum" in schema and data > schema["maximum"]:
                fail(f"value {data} > maximum {schema['maximum']}")
        elif typ == "boolean":
            if not isinstance(data, bool):
                fail("expected boolean")
        else:
            fail(f"unsupported schema type '{typ}'")

def _apply_schema_defaults(data: MutableMapping[str, Any], schema: Mapping[str, Any]) -> None:
    """
    Recursively apply default values from JSON schema to the data dict.
    Only applies defaults for keys that are missing from data.
    """
    if not isinstance(schema, Mapping) or "properties" not in schema:
        return
    
    properties = schema.get("properties", {})
    for key, subschema in properties.items():
        if key not in data and "default" in subschema:
            data[key] = subschema["default"]
        
        # Recurse into nested objects
        if isinstance(subschema, Mapping) and subschema.get("type") == "object":
            if key not in data:
                data[key] = {}
            if isinstance(data[key], MutableMapping):
                _apply_schema_defaults(data[key], subschema)

# -------------------- Config objects --------------------

@dataclass(frozen=True)
class Config:
    data: Dict[str, Any]
    source_path: Optional[Path]
    schema_version: Optional[str]
    config_hash: str

    def get(self, path: str, default: Any = None) -> Any:
        cur: Any = self.data
        for part in path.split("."):
            if not isinstance(cur, Mapping) or part not in cur:
                return default
            cur = cur[part]
        return cur

    def as_dict(self) -> Dict[str, Any]:
        return json.loads(_canonical_json(self.data))  # deep copy via canonical json

class ConfigManager:
    """
    Single Source Of Truth loader with:
      - TOML load
      - ENV override (PREFIX__A__B=val)
      - JSON-schema-lite validation
      - Hot-reload with whitelist of allowed keys
      - Deterministic config_hash
    """
    def __init__(
        self,
        config_path: Optional[Union[str, Path]] = None,
        schema_path: Optional[Union[str, Path]] = None,
        env_prefix: str = "AURORA",
        enable_watcher: bool = False,
        poll_interval_sec: float = 1.5,
        environment: Optional[Mapping[str, str]] = None,
    ) -> None:
        self._env_prefix = env_prefix
        self._env = dict(os.environ if environment is None else environment)
        self._config_path = self._resolve_config_path(config_path)
        self._schema_path = self._resolve_schema_path(schema_path)
        self._whitelist: Set[str] = set()
        self._schema_version: Optional[str] = None
        self._current: Optional[Config] = None
        self._lock = threading.RLock()
        self._watcher_thread: Optional[threading.Thread] = None
        self._stop_evt = threading.Event()
        self._mtime: Optional[float] = None
        self._callbacks: List[Callable[[Config, Set[str]], None]] = []

        # Initial load
        self._load_and_validate(initial=True)

        if enable_watcher:
            self.start_watcher(poll_interval_sec)

    # ---------- public API ----------

    @property
    def config(self) -> Config:
        assert self._current is not None
        return self._current

    def register_callback(self, fn: Callable[[Config, Set[str]], None]) -> None:
        self._callbacks.append(fn)

    def start_watcher(self, poll_interval_sec: float = 1.5) -> None:
        if self._watcher_thread is not None:
            return
        self._stop_evt.clear()
        self._watcher_thread = threading.Thread(target=self._watch_loop, args=(poll_interval_sec,), daemon=True)
        self._watcher_thread.start()

    def stop_watcher(self) -> None:
        if self._watcher_thread is None:
            return
        self._stop_evt.set()
        self._watcher_thread.join(timeout=3.0)
        self._watcher_thread = None

    def try_reload(self) -> Optional[Set[str]]:
        """Manual reload; returns set of changed keys if applied, else None."""
        with self._lock:
            new_data, mtime = self._read_config_file()
            if self._mtime is not None and mtime == self._mtime:
                return None  # no changes
            return self._apply_new_data(new_data, mtime)

    # ---------- internals ----------

    def _resolve_config_path(self, cfg: Optional[Union[str, Path]]) -> Path:
        env_path = os.environ.get(f"{self._env_prefix}_CONFIG")
        p = Path(cfg or env_path or "configs/default.toml")
        return p.absolute()

    def _resolve_schema_path(self, sp: Optional[Union[str, Path]]) -> Optional[Path]:
        if sp is None:
            candidate = Path("configs/schema.json")
            return candidate.absolute() if candidate.exists() else None
        return Path(sp).absolute()

    def _read_config_file(self) -> Tuple[Dict[str, Any], float]:
        if not self._config_path.exists():
            raise ConfigError(f"Config file not found: {self._config_path}")
        raw = self._config_path.read_bytes()
        data = _TOML_LOAD(raw)
        return data, self._config_path.stat().st_mtime

    def _load_schema(self) -> Optional[Dict[str, Any]]:
        if self._schema_path is None:
            return None
        try:
            schema = json.loads(self._schema_path.read_text(encoding="utf-8"))
        except Exception as e:
            raise ConfigError(f"Failed to load schema '{self._schema_path}': {e}")
        self._schema_version = schema.get("$id") or schema.get("version")
        # whitelist may be inside schema or will be read from config later
        wl = schema.get("hotReloadWhitelist") or []
        self._whitelist = set(wl)
        return schema

    def _load_and_validate(self, initial: bool = False) -> None:
        with self._lock:
            data, mtime = self._read_config_file()
            env_override = _parse_env_overrides(self._env_prefix, self._env)
            merged = _deep_merge(data, env_override)

            schema = self._load_schema()
            if schema is not None:
                _validate_schema(merged, schema.get("schema", {"type": "object"}))
                # Apply schema defaults to missing keys
                _apply_schema_defaults(merged, schema.get("schema", {"type": "object"}))

            # If whitelist present in config, join with schema-defined
            cfg_wl = merged.get("hotreload", {}).get("whitelist", [])
            if isinstance(cfg_wl, list):
                self._whitelist |= {str(x) for x in cfg_wl}

            chash = _sha256(_canonical_json(merged))
            self._current = Config(
                data=dict(merged),  # Convert back to Dict for Config dataclass
                source_path=self._config_path,
                schema_version=self._schema_version,
                config_hash=chash,
            )
            self._mtime = mtime
            logger.info("Config loaded (schema=%s, hash=%s…)", self._schema_version, chash[:8])

    def _apply_new_data(self, new_data: Dict[str, Any], new_mtime: float) -> Set[str]:
        assert self._current is not None
        # Apply ENV overrides also on reload
        env_override = _parse_env_overrides(self._env_prefix, self._env)
        new_merged = _deep_merge(new_data, env_override)

        # Validate (same schema)
        schema = self._load_schema()
        if schema is not None:
            _validate_schema(new_merged, schema.get("schema", {"type": "object"}))
            # Apply schema defaults to missing keys
            _apply_schema_defaults(new_merged, schema.get("schema", {"type": "object"}))

        changed = _diff_keys(self._current.data, new_merged)
        # Enforce whitelist: every changed key must start with one of allowed prefixes
        if self._whitelist:
            violations = {k for k in changed if not any(k == w or k.startswith(w + ".") for w in self._whitelist)}
            if violations:
                logger.error("Hot-reload denied; violations: %s", sorted(violations))
                raise HotReloadViolation(f"Non-whitelisted changes: {sorted(violations)[:5]}")

        chash = _sha256(_canonical_json(new_merged))
        self._current = Config(
            data=dict(new_merged),  # Convert back to Dict for Config dataclass
            source_path=self._config_path,
            schema_version=self._schema_version,
            config_hash=chash,
        )
        self._mtime = new_mtime
        logger.info("Hot-reload applied (changed=%d, hash=%s…)", len(changed), chash[:8])
        for cb in self._callbacks:
            try:
                cb(self._current, changed)
            except Exception:  # pragma: no cover
                logger.exception("Reload callback failed")
        return changed

    def _watch_loop(self, poll: float) -> None:  # pragma: no cover (threading)
        while not self._stop_evt.wait(poll):
            try:
                self.try_reload()
            except HotReloadViolation:
                # Keep running; an operator can fix and save again
                pass
            except Exception:
                logger.exception("Watcher reload failed")

# ---------- convenience API ----------

_GLOBAL: Optional[ConfigManager] = None

def load_config(
    config_path: Optional[Union[str, Path]] = None,
    schema_path: Optional[Union[str, Path]] = None,
    env_prefix: str = "AURORA",
    enable_watcher: bool = False,
    poll_interval_sec: float = 1.5,
) -> Config:
    """
    Load global SSOT-config and return read-only Config.
    """
    global _GLOBAL
    _GLOBAL = ConfigManager(
        config_path=config_path,
        schema_path=schema_path,
        env_prefix=env_prefix,
        enable_watcher=enable_watcher,
        poll_interval_sec=poll_interval_sec,
    )
    return _GLOBAL.config

def get_config() -> Config:
    if _GLOBAL is None:
        raise ConfigError("Config not loaded yet. Call load_config() first.")
    return _GLOBAL.config
