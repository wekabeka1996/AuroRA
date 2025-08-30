"""
Aurora Config — JSON Schema (subset) validator with optional defaults application and $ref support.

Features (supported subset):
  - type: object/array/string/number/integer/boolean
  - properties / required / additionalProperties (bool or schema)
  - items (single schema or list), minItems, maxItems, uniqueItems
  - enum, const
  - minimum, maximum, exclusiveMinimum, exclusiveMaximum, multipleOf
  - minLength, maxLength, pattern (ECMAScript-like, compiled to Python re)
  - oneOf, anyOf, allOf, not
  - $ref (local only: "#/definitions/..." or "#/...")
  - $id / version passthrough
  - hotReloadWhitelist passthrough helper

Design goals:
  - Zero external dependencies
  - Deterministic error messages (stable paths like risk.cvar.limit)
  - Safe default application (no mutation of input)

Usage:
    validator = SchemaValidator.from_path("configs/schema.json")
    data_norm = validator.validate(cfg_dict, apply_defaults=True)
    wl = validator.hotreload_whitelist()
    ver = validator.version()
"""
from __future__ import annotations

import json
import re
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple, Union

# -------------------- Exceptions --------------------

class SchemaValidationError(Exception):
    """Raised when configuration fails schema validation."""

class SchemaLoadError(Exception):
    """Raised when schema file cannot be loaded or is invalid."""

# -------------------- Core --------------------

_JSON = Union[Dict[str, Any], List[Any], str, int, float, bool, None]


def _json_pointer(root: Mapping[str, Any], pointer: str) -> Any:
    """Resolve a local JSON Pointer like '#/a/b/0'."""
    if pointer.startswith("#"):
        pointer = pointer[1:]
    if pointer.startswith("/"):
        pointer = pointer[1:]
    cur: Any = root
    if not pointer:
        return cur
    for part in pointer.split("/"):
        part = part.replace("~1", "/").replace("~0", "~")
        if isinstance(cur, Mapping):
            if part not in cur:
                raise SchemaValidationError(f"$ref unresolved at '/{pointer}' (missing '{part}')")
            cur = cur[part]
        elif isinstance(cur, list):
            try:
                idx = int(part)
            except Exception:
                raise SchemaValidationError(f"$ref '/{pointer}' points into array with non-integer index '{part}'")
            try:
                cur = cur[idx]
            except Exception:
                raise SchemaValidationError(f"$ref '/{pointer}' index {idx} out of range")
        else:
            raise SchemaValidationError(f"$ref '/{pointer}' traversed non-container at '{part}'")
    return cur


def _path_join(base: str, key: str) -> str:
    return f"{base}.{key}" if base else key


@dataclass
class _Ctx:
    root_schema: Mapping[str, Any]
    allow_additional: bool


class SchemaValidator:
    def __init__(self, schema: Mapping[str, Any], *, allow_additional_properties: bool = True) -> None:
        if not isinstance(schema, Mapping):
            raise SchemaLoadError("schema must be a mapping")
        self._schema: Mapping[str, Any] = schema
        self._allow_additional = allow_additional_properties
        # cache compiled regex patterns to avoid recompilation
        self._re_cache: Dict[str, re.Pattern[str]] = {}

    # -------- Construction helpers --------

    @classmethod
    def from_path(cls, path: Union[str, Path], *, allow_additional_properties: bool = True) -> "SchemaValidator":
        p = Path(path)
        try:
            obj = json.loads(p.read_text(encoding="utf-8"))
        except Exception as e:
            raise SchemaLoadError(f"failed to load schema '{p}': {e}")
        return cls(obj, allow_additional_properties=allow_additional_properties)

    # -------- Public API --------

    def version(self) -> Optional[str]:
        return self._schema.get("$id") or self._schema.get("version")

    def raw(self) -> Mapping[str, Any]:
        return self._schema

    def hotreload_whitelist(self) -> List[str]:
        wl = self._schema.get("hotReloadWhitelist")
        return list(wl) if isinstance(wl, list) else []

    def validate(self, data: _JSON, *, apply_defaults: bool = False) -> _JSON:
        """
        Validate `data` against schema root (key 'schema' if present else whole doc).
        Returns a **new** normalized object when apply_defaults=True, else returns input (unmodified).
        Raises SchemaValidationError on first failure (fail-fast, deterministic paths).
        """
        root = self._schema.get("schema", self._schema)
        ctx = _Ctx(root_schema=root, allow_additional=self._allow_additional)
        value = deepcopy(data) if apply_defaults else data
        out = self._validate_node(value, root, path="", ctx=ctx, apply_defaults=apply_defaults)
        return out

    # -------- Internal validation --------

    def _validate_node(self, value: Any, schema: Mapping[str, Any], *, path: str, ctx: _Ctx, apply_defaults: bool) -> Any:
        # $ref resolution (local only)
        if "$ref" in schema:
            ref = schema["$ref"]
            if not isinstance(ref, str):
                raise SchemaValidationError(f"{path or '$'}: $ref must be string")
            target = _json_pointer(ctx.root_schema, ref)
            if not isinstance(target, Mapping):
                raise SchemaValidationError(f"{path or '$'}: $ref must target an object schema")
            return self._validate_node(value, target, path=path, ctx=ctx, apply_defaults=apply_defaults)

        typ = schema.get("type")
        if typ is None:
            # if schema is a composition without type, still apply compositions/const/enum
            pass
        else:
            self._enforce_type(value, typ, path)

        # compositions first (fail-fast with precise path)
        if "allOf" in schema:
            for i, sub in enumerate(schema["allOf"]):
                value = self._validate_node(value, sub, path=path, ctx=ctx, apply_defaults=apply_defaults)
        if "anyOf" in schema:
            errors: List[str] = []
            for sub in schema["anyOf"]:
                try:
                    self._validate_node(value, sub, path=path, ctx=ctx, apply_defaults=apply_defaults)
                    errors = []
                    break
                except SchemaValidationError as e:
                    errors.append(str(e))
            if errors:
                raise SchemaValidationError(f"{path or '$'}: failed anyOf; reasons: {errors[:2]}")
        if "oneOf" in schema:
            matches = 0
            last_val = value
            last_err: Optional[str] = None
            for sub in schema["oneOf"]:
                try:
                    last_val = self._validate_node(value, sub, path=path, ctx=ctx, apply_defaults=apply_defaults)
                    matches += 1
                except SchemaValidationError as e:
                    last_err = str(e)
            if matches != 1:
                raise SchemaValidationError(f"{path or '$'}: expected exactly one schema in oneOf to match (got {matches}); last_err={last_err}")
            value = last_val
        if "not" in schema:
            try:
                self._validate_node(value, schema["not"], path=path, ctx=ctx, apply_defaults=False)
            except SchemaValidationError:
                pass  # good: does not match
            else:
                raise SchemaValidationError(f"{path or '$'}: value must not match schema in 'not'")

        # enums / const
        if "enum" in schema:
            enum = schema["enum"]
            if value not in enum:
                raise SchemaValidationError(f"{path or '$'}: value {value!r} not in enum {enum}")
        if "const" in schema:
            if value != schema["const"]:
                raise SchemaValidationError(f"{path or '$'}: value {value!r} != const {schema['const']!r}")

        # Type-specific constraints
        if typ == "object" or (typ is None and isinstance(value, dict)):
            return self._validate_object(value, schema, path=path, ctx=ctx, apply_defaults=apply_defaults)
        if typ == "array" or (typ is None and isinstance(value, list)):
            return self._validate_array(value, schema, path=path, ctx=ctx, apply_defaults=apply_defaults)
        if typ == "string" or (typ is None and isinstance(value, str)):
            self._validate_string(value, schema, path)
            return value
        if typ == "number" or (typ is None and isinstance(value, (int, float))):
            self._validate_number(value, schema, path, integer=False)
            return value
        if typ == "integer" or (typ is None and isinstance(value, int) and not isinstance(value, bool)):
            self._validate_number(value, schema, path, integer=True)
            return value
        if typ == "boolean" or (typ is None and isinstance(value, bool)):
            return value
        if typ == "null" or (typ is None and value is None):
            return value

        return value

    # ----- primitive validators -----

    def _enforce_type(self, value: Any, typ: str, path: str) -> None:
        ok = False
        if typ == "object":
            ok = isinstance(value, Mapping)
        elif typ == "array":
            ok = isinstance(value, list)
        elif typ == "string":
            ok = isinstance(value, str)
        elif typ == "number":
            ok = isinstance(value, (int, float)) and not isinstance(value, bool)
        elif typ == "integer":
            ok = isinstance(value, int) and not isinstance(value, bool)
        elif typ == "boolean":
            ok = isinstance(value, bool)
        elif typ == "null":
            ok = value is None
        else:
            raise SchemaValidationError(f"{path or '$'}: unsupported schema type '{typ}'")
        if not ok:
            raise SchemaValidationError(f"{path or '$'}: expected {typ}, got {type(value).__name__}")

    def _validate_number(self, value: Union[int, float], schema: Mapping[str, Any], path: str, *, integer: bool) -> None:
        if integer and not (isinstance(value, int) and not isinstance(value, bool)):
            raise SchemaValidationError(f"{path or '$'}: expected integer")
        if "multipleOf" in schema:
            m = schema["multipleOf"]
            try:
                if (value / m) % 1 != 0:
                    raise SchemaValidationError(f"{path or '$'}: {value} not multipleOf {m}")
            except Exception:
                raise SchemaValidationError(f"{path or '$'}: invalid multipleOf {m}")
        for key, op in (("minimum", lambda a, b: a < b), ("maximum", lambda a, b: a > b)):
            if key in schema:
                bound = schema[key]
                if op(value, bound):
                    raise SchemaValidationError(f"{path or '$'}: value {value} violates {key} {bound}")
        for key, strict, op in (
            ("exclusiveMinimum", True, lambda a, b: a <= b),
            ("exclusiveMaximum", True, lambda a, b: a >= b),
        ):
            if key in schema:
                bound = schema[key]
                if op(value, bound):
                    raise SchemaValidationError(f"{path or '$'}: value {value} violates {key} {bound}")

    def _validate_string(self, value: str, schema: Mapping[str, Any], path: str) -> None:
        if "minLength" in schema and len(value) < int(schema["minLength"]):
            raise SchemaValidationError(f"{path or '$'}: string shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(value) > int(schema["maxLength"]):
            raise SchemaValidationError(f"{path or '$'}: string longer than maxLength {schema['maxLength']}")
        if "pattern" in schema:
            pat = schema["pattern"]
            if pat not in self._re_cache:
                try:
                    self._re_cache[pat] = re.compile(pat)
                except re.error as e:
                    raise SchemaValidationError(f"{path or '$'}: invalid regex pattern '{pat}': {e}")
            if not self._re_cache[pat].search(value):
                raise SchemaValidationError(f"{path or '$'}: value does not match pattern '{pat}'")

    def _validate_array(self, value: List[Any], schema: Mapping[str, Any], *, path: str, ctx: _Ctx, apply_defaults: bool) -> List[Any]:
        if "minItems" in schema and len(value) < int(schema["minItems"]):
            raise SchemaValidationError(f"{path or '$'}: array length {len(value)} < minItems {schema['minItems']}")
        if "maxItems" in schema and len(value) > int(schema["maxItems"]):
            raise SchemaValidationError(f"{path or '$'}: array length {len(value)} > maxItems {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen = set()
            for i, item in enumerate(value):
                key = json.dumps(item, sort_keys=True) if isinstance(item, (dict, list)) else item
                if key in seen:
                    raise SchemaValidationError(f"{_path_join(path, str(i))}: duplicate item with uniqueItems=true")
                seen.add(key)
        items = schema.get("items")
        out = value if not apply_defaults else list(value)
        if isinstance(items, list):
            for i, (item, sub) in enumerate(zip(value, items)):
                norm = self._validate_node(item, sub, path=_path_join(path, str(i)), ctx=ctx, apply_defaults=apply_defaults)
                if apply_defaults:
                    out[i] = norm
            # Additional items not allowed unless additionalItems (deprecated) or no constraint
            if len(value) > len(items):
                raise SchemaValidationError(f"{path or '$'}: additional array items beyond defined tuple schema")
        elif isinstance(items, Mapping):
            for i, item in enumerate(value):
                norm = self._validate_node(item, items, path=_path_join(path, str(i)), ctx=ctx, apply_defaults=apply_defaults)
                if apply_defaults:
                    out[i] = norm
        return out

    def _validate_object(self, value: Mapping[str, Any], schema: Mapping[str, Any], *, path: str, ctx: _Ctx, apply_defaults: bool) -> Dict[str, Any]:
        props: Mapping[str, Any] = schema.get("properties", {}) if isinstance(schema.get("properties"), Mapping) else {}
        required: List[str] = list(schema.get("required", []))
        addl = schema.get("additionalProperties", self._allow_additional)
        out: Dict[str, Any] = dict(value) if not apply_defaults else dict(value)  # Always start with input data

        # First, apply defaults for missing properties
        for k, subschema in props.items():
            if k not in value and apply_defaults and isinstance(subschema, Mapping) and "default" in subschema:
                out[k] = deepcopy(subschema["default"])  # apply default

        # Now check required keys (after defaults have been applied)
        for r in required:
            if r not in out:
                raise SchemaValidationError(f"{_path_join(path, r)}: missing required key")

        # known properties
        for k, subschema in props.items():
            if k in out:  # Check in out, not value, since defaults may have been added
                norm = self._validate_node(out[k], subschema, path=_path_join(path, k), ctx=ctx, apply_defaults=apply_defaults)
                out[k] = norm

        # additional properties
        for k, v in value.items():
            if k in props:
                continue
            if addl is False:
                raise SchemaValidationError(f"{_path_join(path, k)}: additionalProperties not allowed")
            elif addl is True or addl is None:
                if apply_defaults:
                    out[k] = deepcopy(v)
            elif isinstance(addl, Mapping):
                norm = self._validate_node(v, addl, path=_path_join(path, k), ctx=ctx, apply_defaults=apply_defaults)
                if apply_defaults:
                    out[k] = norm
            else:
                raise SchemaValidationError(f"{_path_join(path, k)}: invalid additionalProperties spec")

        return out
