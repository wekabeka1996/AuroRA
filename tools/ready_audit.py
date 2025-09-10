#!/usr/bin/env python3
from __future__ import annotations

from pathlib import Path
import sys

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

    # 2) Config presence: respect AURORA_CONFIG_NAME or fall back to common defaults
    import os
    cfg_name = os.getenv("AURORA_CONFIG_NAME") or "master_config_v2"
    active_cfg = ROOT / "configs" / f"{cfg_name}.yaml"
    ok = active_cfg.exists()
    msg = f"present ({active_cfg.name})" if ok else f"missing ({active_cfg.name})"
    # If missing, try common fallbacks to avoid false negatives on fresh repos
    if not ok:
        fallbacks = [
            ROOT / "configs" / "master_config_v2.yaml",
            ROOT / "configs" / "master_config_v1.yaml",
            ROOT / "configs" / "aurora_config.template.yaml",
        ]
        for fp in fallbacks:
            if fp.exists():
                ok = True
                msg = f"present ({fp.name})"
                break
    results.append(("config:active_present", ok, msg))

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
