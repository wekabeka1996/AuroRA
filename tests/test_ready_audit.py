from subprocess import run
from sys import executable
from pathlib import Path


def test_ready_audit_runs(tmp_path: Path):
    # just ensure script executes and produces a file
    from pathlib import Path as P
    # run in repo root
    p = run([executable, str(P('tools')/'ready_audit.py')])
    assert p.returncode in (0,1)
    assert (P('artifacts')/'ready_audit_report.md').exists()
