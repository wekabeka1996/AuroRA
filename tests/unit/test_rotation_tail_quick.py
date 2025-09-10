import sys
import subprocess


def test_rotation_quick(tmp_path):
    # run rotation script with tiny params and capture stdout
    out = tmp_path / "rot.log"
    cmd = [sys.executable, "tools/test_rotation.py", "--log-name", "test_rotation_quick", "--max-mb", "0.01", "--retention", "2", "--rounds", "1", "--dir", str(tmp_path)]
    subprocess.check_call(cmd)
    # expect rotation output file present
    found = any(p.name.endswith('.gz') for p in tmp_path.glob('test_rotation_quick*'))
    assert found, "rotation gz files not created"

import sys, subprocess, pathlib

def test_rotation_quick(tmp_path):
    logdir = pathlib.Path("logs")
    logdir.mkdir(exist_ok=True)
    out = logdir / "rotation_quick.txt"
    cmd = [sys.executable, "tools/test_rotation.py", "--log-name", "test_rotation_quick",
           "--max-mb", "0.1", "--retention", "2", "--rounds", "1"]
    r = subprocess.run(cmd, capture_output=True, text=True)
    out.write_text(r.stdout)
    assert "ROTATION_OK" in out.read_text()
