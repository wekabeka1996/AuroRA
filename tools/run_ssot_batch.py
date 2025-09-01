#!/usr/bin/env python3
"""Batch runner: import ssot_validate once and run main() for multiple configs,
capturing stdout/stderr and SystemExit codes into logs/*."""
from __future__ import annotations
import sys
from pathlib import Path
import io
from contextlib import redirect_stdout, redirect_stderr

ROOT = Path(__file__).resolve().parent.parent
LOGS = ROOT / 'logs'
LOGS.mkdir(exist_ok=True)

configs = [
    ROOT / 'configs' / 'tests' / 'ok.toml',
    ROOT / 'configs' / 'tests' / 'neg_missing.toml',
    ROOT / 'configs' / 'tests' / 'neg_unknown.toml',
    ROOT / 'configs' / 'tests' / 'neg_nulls.toml',
    ROOT / 'configs' / 'tests' / 'neg_invariants.toml',
    ROOT / 'configs' / 'tests' / 'neg_schema.toml',
]

# import the validator module once
try:
    import tools.ssot_validate as sv
except Exception as e:
    # if import fails, print to logs and exit
    msg = f"IMPORT_FAIL: {e}\n"
    (LOGS / 'ssot_batch_import_fail.txt').write_text(msg, encoding='utf-8')
    raise

for cfg in configs:
    name = cfg.stem
    out_path = LOGS / f'ssot_{name}.txt'
    exit_path = LOGS / f'ssot_{name}.exit'
    buf = io.StringIO()
    code = 0
    try:
        with redirect_stdout(buf), redirect_stderr(buf):
            old_argv = sys.argv
            sys.argv = ['tools/ssot_validate.py', '--config', str(cfg)]
            try:
                sv.main()
                code = 0
            except SystemExit as e:
                # SystemExit may carry code or message
                try:
                    code = int(e.code)
                except Exception:
                    # non-int codes treated as 1
                    code = 1
            finally:
                sys.argv = old_argv
    except Exception as e:
        buf.write(f"RUN_ERROR: {e}\n")
        code = 1
    # write outputs
    out_text = buf.getvalue()
    out_path.write_text(out_text, encoding='utf-8')
    exit_path.write_text(str(code), encoding='utf-8')
    print(f"WROTE {out_path} EXIT={code}")

print("BATCH_RUN_COMPLETE")
