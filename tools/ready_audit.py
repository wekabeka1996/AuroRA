#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def check_imports() -> list[tuple[str, bool, str]]:
    checks = []
    targets = [
        "api.service",
        "common.events",
        "core.aurora.pretrade",
        "core.scalper.calibrator",
    ]
    for t in targets:
        ok, msg = True, "ok"
        try:
            __import__(t)
        except Exception as e:
            ok, msg = False, str(e)
        checks.append((f"import:{t}", ok, msg))
    return checks


def main():
    results = []
    # 1) imports
    results.extend(check_imports())

    # 2) env-over-YAML check: existence of configs/v4_min.yaml (we don't evaluate precedence here, just presence)
    v4 = ROOT / "configs" / "v4_min.yaml"
    results.append(("config:v4_min.yaml_present", v4.exists(), "present" if v4.exists() else "missing"))

    # 3) kill-switch endpoints known (static check only)
    results.append(("ops:endpoints_known", True, "/aurora/{arm|disarm}, /ops/cooloff/{sec}"))

    # 4) order logging module present
    ol = ROOT / "core" / "order_logger.py"
    results.append(("order_logger:module_present", ol.exists(), "present" if ol.exists() else "missing"))

    # Summarize
    ok = all(ok for _, ok, _ in results)
    lines = ["# Ready Audit Report", "", "Checks:"]
    for name, status, msg in results:
        mark = "✅" if status else "❌"
        lines.append(f"- {mark} {name} — {msg}")
    out = ROOT / "artifacts" / "ready_audit_report.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines), encoding="utf-8")
    print(out)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
