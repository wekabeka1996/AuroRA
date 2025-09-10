from __future__ import annotations

import argparse
import sys
from typing import Any

import yaml


def validate(cfg: dict[str, Any], fail_unknown: bool = False) -> list[str]:
    errs: list[str] = []
    # unknown keys (optional strict)
    if fail_unknown:
        allowed_top = {
            "env", "symbols", "reward", "dq",
            "aurora", "policy_shim", "chat", "logging", "risk", "slippage", "sprt", "trap", "guards", "gates", "pretrade", "trading", "api", "security", "observability"
        }
        for k in cfg.keys():
            if k not in allowed_top:
                errs.append(f"Unknown top-level key: {k}")
    # specific checks (only if present)
    pre = cfg.get("pretrade", {}) or {}
    if "order_profile" in pre and pre["order_profile"] not in ("er_before_slip", "slip_before_er"):
        errs.append("pretrade.order_profile must be 'er_before_slip' or 'slip_before_er'")
    aur = cfg.get("aurora", {}) or {}
    if "latency_guard_ms" in aur and not isinstance(aur["latency_guard_ms"], (int, float)):
        errs.append("aurora.latency_guard_ms must be a number")
    # ... extend as needed
    return errs


def main():
    p = argparse.ArgumentParser()
    p.add_argument('files', nargs='+')
    p.add_argument('--strict', action='store_true')
    p.add_argument('--fail-unknown', action='store_true')
    args = p.parse_args()

    failed = False
    for fp in args.files:
        try:
            with open(fp, encoding='utf-8') as f:
                cfg = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"Failed to read {fp}: {e}")
            failed = True
            continue
        errs = validate(cfg, fail_unknown=args.fail_unknown)
        if errs:
            print(f"Config {fp} has issues:")
            for e in errs:
                print("-", e)
            if args.strict:
                failed = True
    if failed:
        sys.exit(1)
    print("Config validation OK")


if __name__ == '__main__':
    main()
