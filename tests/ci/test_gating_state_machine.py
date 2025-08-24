from pathlib import Path
from living_latent.core.ci.gating import CIGatingStateMachine, MetricSpec
import tempfile, shutil, json


def make_sm(tmp: Path):
    cfg = dict(window_runs=5, enter_warn_runs=2, exit_warn_runs=2, enter_watch_runs=1, cooldown_runs=2, enabled=True)
    specs = [MetricSpec(name='metric1', source_key='m1', threshold_key='thr.m1', relation='<=', hard_candidate=True)]
    sm = CIGatingStateMachine(cfg, specs, persistence_path=tmp/'gating.jsonl')
    return sm


def test_enters_warn_after_consecutive_violations():
    t = Path(tempfile.mkdtemp())
    try:
        sm = make_sm(t)
        thresholds = {'thr': {'m1': 1.0}}
        # first violation (value 2.0 > 1.0 for '<=')
        ev1 = sm.evaluate_batch('r1', {'m1': 2.0}, thresholds)[0]
        assert ev1.state_after == 'observe'  # not yet warn
        ev2 = sm.evaluate_batch('r2', {'m1': 2.0}, thresholds)[0]
        assert ev2.state_after in ('warn','watch')  # after second violation warn/watch
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_exits_warn_after_clean_runs():
    t = Path(tempfile.mkdtemp())
    try:
        sm = make_sm(t)
        thresholds = {'thr': {'m1': 1.0}}
        sm.evaluate_batch('r1', {'m1': 2.0}, thresholds)
        sm.evaluate_batch('r2', {'m1': 2.0}, thresholds)
        # now ok runs
        ev3 = sm.evaluate_batch('r3', {'m1': 0.5}, thresholds)[0]
        ev4 = sm.evaluate_batch('r4', {'m1': 0.4}, thresholds)[0]
        assert ev4.state_after in ('stable','cooldown','observe')
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_unknown_when_missing():
    t = Path(tempfile.mkdtemp())
    try:
        sm = make_sm(t)
        thresholds = {'thr': {}}  # missing threshold
        ev = sm.evaluate_batch('rX', {'m1': 0.5}, thresholds)[0]
        assert ev.state_after == 'unknown'
    finally:
        shutil.rmtree(t, ignore_errors=True)


def test_persistence():
    t = Path(tempfile.mkdtemp())
    try:
        sm = make_sm(t)
        thresholds = {'thr': {'m1': 1.0}}
        sm.evaluate_batch('r1', {'m1': 2.0}, thresholds)
        sm.evaluate_batch('r2', {'m1': 2.0}, thresholds)
        content = (t/'gating.jsonl').read_text(encoding='utf-8').strip().splitlines()
        assert len(content) == 2
        rec = json.loads(content[-1])
        assert rec['metric'] == 'metric1'
    finally:
        shutil.rmtree(t, ignore_errors=True)
