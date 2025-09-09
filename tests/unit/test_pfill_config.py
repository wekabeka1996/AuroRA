import math
from decimal import Decimal


def test_pfill_config_aliases_top_level():
    from core.execution.router_v2 import RouterV2

    cfg = {
        "pfill": {
            "beta": {"beta0": -2.0, "b1": 1.0, "beta2": 2.0, "beta3": 0.5, "beta4": 0.7},
            "eps": 0.0003,
        },
        "execution": {
            "router": {
                "pfill_min": 0.66,
            }
        }
    }

    r = RouterV2(config=cfg)

    # Aliases resolved and stored as floats
    assert isinstance(r._pfill_beta, dict)
    assert {"b0", "b1", "b2", "b3", "b4"}.issubset(r._pfill_beta.keys())
    assert math.isclose(r._pfill_beta["b0"], -2.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r._pfill_beta["b1"], 1.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r._pfill_beta["b2"], 2.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r._pfill_beta["b3"], 0.5, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r._pfill_beta["b4"], 0.7, rel_tol=0, abs_tol=1e-12)

    # Eps parsed
    assert r._pfill_eps is not None and math.isclose(r._pfill_eps, 3e-4, rel_tol=0, abs_tol=1e-12)

    # pfill_min wired to Decimal
    assert isinstance(r.pi_fill_min, Decimal)
    assert r.pi_fill_min == Decimal("0.66")


def test_pfill_config_execution_overrides_top_level():
    from core.execution.router_v2 import RouterV2

    cfg = {
        "pfill": {
            "beta": {"b0": -2.0},
            "eps": 0.0003,
        },
        "execution": {
            "pfill": {
                "beta": {"b0": -3.0, "b1": 1.1},
                "eps": 0.0005,
            },
            "router": {
                "pfill_min": 0.5,
            }
        }
    }

    r = RouterV2(config=cfg)

    # execution.pfill overrides top-level pfill
    assert isinstance(r._pfill_beta, dict)
    assert math.isclose(r._pfill_beta.get("b0", 0.0), -3.0, rel_tol=0, abs_tol=1e-12)
    assert math.isclose(r._pfill_beta.get("b1", 0.0), 1.1, rel_tol=0, abs_tol=1e-12)

    # eps overridden
    assert r._pfill_eps is not None and math.isclose(r._pfill_eps, 5e-4, rel_tol=0, abs_tol=1e-12)

    # sanity: pfill_min parsed
    assert r.pi_fill_min == Decimal("0.5")
