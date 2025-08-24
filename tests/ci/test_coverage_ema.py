import json
import math
from pathlib import Path
import tempfile

import pytest

from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec


def compute_ema(seq, beta, ema0=0.0):
    ema = ema0
    out = []
    for x in seq:
        ema = (1 - beta) * ema + beta * x
        out.append(ema)
    return out


def test_ema_basic_constant_series():
    x = [0.10] * 20
    beta = 0.2
    ema_vals = compute_ema(x, beta, ema0=0.0)
    # Monotonic non-decreasing
    assert all(ema_vals[i] <= ema_vals[i+1] + 1e-12 for i in range(len(ema_vals)-1))
    # After 20 steps with beta=0.2, error should be small (<0.01)
    assert abs(ema_vals[-1] - 0.10) < 1e-2


def test_ema_step_change():
    beta = 0.2
    seq = [0.0]*10 + [0.2]*10
    ema_vals = compute_ema(seq, beta, ema0=0.0)
    # After step (index 10 is first 0.2) check point at 15 (0-based) which is 6th after step
    val_at_15 = ema_vals[15]
    # Expect partial adaptation (not too low / not almost full)
    assert 0.10 <= val_at_15 <= 0.18, f"EMA reacted too fast/slow: {val_at_15}"
    assert ema_vals[-1] > val_at_15  # keeps moving toward 0.2


def test_ema_persistence_statefile(tmp_path: Path):
    # Simulate two runs persisting state
    beta = 0.2
    state_file = tmp_path / 'coverage_ema.state'
    seq1 = [0.1,0.1,0.1,0.1,0.1]
    ema: float = seq1[0]
    # run1 (first value seeds ema explicitly)
    for v in seq1[1:]:
        ema = (1-beta)*ema + beta*v
    state_file.write_text(json.dumps({'coverage_abs_err_ema': ema}))
    ema_after_run1 = ema
    # run2 continues
    seq2 = [0.1,0.1,0.1,0.1,0.1]
    for v in seq2:
        ema = (1-beta)*ema + beta*v
    assert ema > ema_after_run1 - 1e-12  # non-decreasing for constant sequence above ema0


def _fake_thresholds(thr):
    return {'ci': {'coverage_tolerance': {'max': thr}}}


def test_gating_violation_generation():
    cfg = {
        'window_runs': 5,
        'enter_warn_runs': 2,
        'exit_warn_runs': 3,
        'enter_watch_runs': 1,
        'cooldown_runs': 3
    }
    specs = [MetricSpec(
        name='coverage_abs_err_ema',
        source_key='ci.coverage_abs_err_ema',
        threshold_key='ci.coverage_tolerance.max',
        relation='<=',
        hard_candidate=False
    )]
    sm = CIGatingStateMachine(cfg, specs)

    # coverage_abs_err sequence; we feed pre-computed EMA values to mimic runs
    # For simplicity treat provided values as already EMA (monotonic logic similar for gating)
    values = [0.12, 0.10, 0.03, 0.11, 0.12]
    thresholds = _fake_thresholds(0.08)
    events_all = []
    for i, v in enumerate(values):
        summary = {'ci': {'coverage_abs_err_ema': v}}
        evs = sm.evaluate_batch(f'run{i}', summary, thresholds)
        events_all.extend(evs)

    # Find first transition observe->warn
    trans = [e for e in events_all if e.state_before == 'observe' and e.state_after in ('warn','watch')]
    assert trans, 'No warn transition emitted'
    first = trans[0]
    # It should occur at second consecutive violation (index 1)
    assert first.run_id == 'run1'
    assert first.violation is True
    assert first.metric == 'coverage_abs_err_ema'
    assert first.threshold == 0.08
    assert first.relation == '<='
    assert 'CI-GATING' in first.message


def test_gating_unknown_on_missing_values():
    cfg = {'window_runs':5}
    specs = [MetricSpec(
        name='coverage_abs_err_ema', source_key='ci.coverage_abs_err_ema', threshold_key='ci.coverage_tolerance.max'
    )]
    sm = CIGatingStateMachine(cfg, specs)
    # Missing value
    thresholds = _fake_thresholds(0.08)
    evs = sm.evaluate_batch('run0', {}, thresholds)
    ev = evs[0]
    assert ev.state_after == 'unknown'
    assert not ev.violation


def test_prometheus_exported(monkeypatch):
    # Minimal fake exporter collecting set values
    class FakeExporter:
        def __init__(self):
            self.values = {}
        def set_ci_gating_state(self, metric, state):
            self.values[f'state:{metric}'] = state
        def set_ci_gating_value(self, metric, value):
            self.values[f'value:{metric}'] = value
        def set_ci_gating_threshold(self, metric, thr):
            self.values[f'thr:{metric}'] = thr
        def inc_ci_gating_violation(self, metric):
            self.values[f'viol:{metric}'] = self.values.get(f'viol:{metric}',0)+1

    cfg = {'enter_warn_runs':1}
    specs = [MetricSpec(name='coverage_abs_err_ema', source_key='ci.coverage_abs_err_ema', threshold_key='ci.coverage_tolerance.max')]
    fe = FakeExporter()
    sm = CIGatingStateMachine(cfg, specs, metrics_exporter=fe)
    thresholds = _fake_thresholds(0.05)
    sm.evaluate_batch('run0', {'ci': {'coverage_abs_err_ema':0.10}}, thresholds)
    assert fe.values['state:coverage_abs_err_ema'] in ('warn','watch','observe','unknown')
    assert fe.values['value:coverage_abs_err_ema'] == 0.10
    assert fe.values['thr:coverage_abs_err_ema'] == 0.05
