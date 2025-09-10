import json
import subprocess
import sys


def test_rotation_retention_and_lastline(tmp_path):
    # Run rotation script with retention=2
    cmd = [
        sys.executable, "tools/test_rotation.py",
        "--log-name", "test_retention",
        "--max-mb", "0.01",
        "--retention", "2",
        "--rounds", "1",
        "--dir", str(tmp_path)
    ]
    result = subprocess.run(cmd, capture_output=True, text=True)
    assert result.returncode == 0

    # Check that gz files exist
    gz_files = list(tmp_path.glob("test_retention*.gz"))
    assert len(gz_files) > 0

    # Check last line of each gz is valid JSON
    import gzip
    for gz in gz_files:
        with gzip.open(gz, 'rt') as f:
            lines = f.readlines()
            if lines:
                last_line = lines[-1].strip()
                json.loads(last_line)  # Should not raise
