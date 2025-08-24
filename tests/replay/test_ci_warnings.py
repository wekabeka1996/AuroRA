import json

from living_latent.core.replay.summarize import compute_warnings


def test_warnings_do_not_fail_and_list_metrics():
    cfg = {
        "alpha_target": 0.1,
        "coverage_tolerance": 0.03,
        "ctr_min": 0.95,
        "dcts_min": 0.9,
        "max_churn_per_1k": 25,
        "warnings": {
            "warn_fraction": 0.8,
            "lower_bound_metrics": ["coverage_empirical", "ctr", "dcts"],
            "upper_bound_metrics": ["decision_churn_per_1k"],
        },
    }
    # Значения подобраны так, чтобы churn попал в зону предупреждения, но не violation.
    summary = {
        "coverage_empirical": 0.93,        # хорошо выше нижней границы
        "decision_churn_per_1k": 22.0,     # 22 / 25 = 0.88 -> warning (>=0.8*thr, < thr)
        "ctr": 0.960,                      # выше минимального -> no warning
        "dcts": 0.905,                     # чуть выше минимального -> возможно no warning
    }

    warns = compute_warnings(summary, cfg)
    assert "decision_churn_per_1k" in warns
    # Не должно быть предупреждения по coverage_empirical
    assert "coverage_empirical" not in warns
