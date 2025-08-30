import pytest

from core.config.schema_validator import SchemaValidator, SchemaValidationError


def test_apply_defaults_and_required():
    schema = {
        "schema": {
            "type": "object",
            "properties": {
                "risk": {
                    "type": "object",
                    "properties": {
                        "cvar": {
                            "type": "object",
                            "properties": {
                                "limit": {"type": "number", "default": 0.02},
                                "horizon": {"type": "integer", "default": 250},
                            },
                            "required": ["limit"],
                        }
                    },
                    "required": ["cvar"],
                }
            },
            "required": ["risk"],
        }
    }
    data = {"risk": {"cvar": {}}}
    v = SchemaValidator(schema)
    out = v.validate(data, apply_defaults=True)
    assert out["risk"]["cvar"]["limit"] == 0.02
    assert out["risk"]["cvar"]["horizon"] == 250

    # missing required section
    with pytest.raises(SchemaValidationError):
        v.validate({}, apply_defaults=False)


def test_ref_resolution():
    schema = {
        "schema": {
            "type": "object",
            "definitions": {
                "latency": {
                    "type": "object",
                    "properties": {
                        "max_latency_ms": {"type": "integer", "minimum": 0, "default": 25}
                    },
                    "required": ["max_latency_ms"],
                }
            },
            "properties": {
                "execution": {"$ref": "#/definitions/latency"}
            },
            "required": ["execution"],
        }
    }
    data = {"execution": {}}
    v = SchemaValidator(schema)
    out = v.validate(data, apply_defaults=True)
    assert out["execution"]["max_latency_ms"] == 25


def test_anyof_oneof_not_and_allof():
    schema = {
        "schema": {
            "type": "object",
            "properties": {
                "alpha": {"anyOf": [{"type": "string"}, {"type": "integer"}]},
                "beta": {"oneOf": [{"type": "integer"}, {"type": "string"}]},
                "gamma": {"allOf": [{"type": "number"}, {"minimum": 0}]},
                "delta": {"not": {"type": "null"}},
            },
        }
    }
    v = SchemaValidator(schema)

    # anyOf passes with integer
    out = v.validate({"alpha": 5}, apply_defaults=False)
    assert out["alpha"] == 5

    # oneOf — exactly one match
    out = v.validate({"beta": 7}, apply_defaults=False)
    assert out["beta"] == 7

    # oneOf failure: matches none
    with pytest.raises(SchemaValidationError):
        v.validate({"beta": 7.5}, apply_defaults=False)

    # allOf: number and minimum >= 0
    out = v.validate({"gamma": 0.1}, apply_defaults=False)
    assert out["gamma"] == 0.1

    # not: must not be null
    with pytest.raises(SchemaValidationError):
        v.validate({"delta": None}, apply_defaults=False)


def test_additional_properties_boolean_and_schema():
    schema = {
        "schema": {
            "type": "object",
            "properties": {
                "strict": {
                    "type": "object",
                    "properties": {"a": {"type": "integer"}},
                    "additionalProperties": False,
                },
                "loose": {
                    "type": "object",
                    "additionalProperties": {"type": "number", "minimum": 0},
                },
            },
        }
    }
    v = SchemaValidator(schema)

    # Additional forbidden
    with pytest.raises(SchemaValidationError):
        v.validate({"strict": {"a": 1, "x": 2}}, apply_defaults=False)

    # Additional allowed with schema
    out = v.validate({"loose": {"x": 2.5, "y": 0}}, apply_defaults=False)
    assert out["loose"]["x"] == 2.5 and out["loose"]["y"] == 0

    # Additional violates schema
    with pytest.raises(SchemaValidationError):
        v.validate({"loose": {"bad": -1}}, apply_defaults=False)


def test_array_constraints_and_items():
    schema = {
        "schema": {
            "type": "object",
            "properties": {
                "ticks": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 4,
                    "uniqueItems": True,
                },
                "pair": {
                    "type": "array",
                    "items": [{"type": "string"}, {"type": "integer"}],
                },
            },
        }
    }
    v = SchemaValidator(schema)

    # valid array
    out = v.validate({"ticks": [1, 2, 3]}, apply_defaults=False)
    assert out["ticks"] == [1, 2, 3]

    # uniqueItems violation
    with pytest.raises(SchemaValidationError):
        v.validate({"ticks": [1, 1]}, apply_defaults=False)

    # tuple-typed items: extra item should fail
    with pytest.raises(SchemaValidationError):
        v.validate({"pair": ["BTCUSDT", 5, 99]}, apply_defaults=False)


def test_string_and_number_constraints():
    schema = {
        "schema": {
            "type": "object",
            "properties": {
                "sym": {"type": "string", "minLength": 3, "maxLength": 10, "pattern": "^[A-Z]+$"},
                "th": {
                    "type": "number",
                    "minimum": 0.0,
                    "maximum": 1.0,
                    "exclusiveMinimum": 0.0,
                    "exclusiveMaximum": 1.0,
                    "multipleOf": 0.05,
                },
            },
        }
    }
    v = SchemaValidator(schema)

    out = v.validate({"sym": "BTC", "th": 0.5}, apply_defaults=False)
    assert out["sym"] == "BTC" and out["th"] == 0.5

    # pattern fail
    with pytest.raises(SchemaValidationError):
        v.validate({"sym": "btC"}, apply_defaults=False)

    # boundary fails for exclusive and multipleOf
    with pytest.raises(SchemaValidationError):
        v.validate({"th": 0.0}, apply_defaults=False)
    with pytest.raises(SchemaValidationError):
        v.validate({"th": 1.0}, apply_defaults=False)
    with pytest.raises(SchemaValidationError):
        v.validate({"th": 0.51}, apply_defaults=False)
