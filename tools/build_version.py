"""Utilities to build a structured version record for Aurora.

Centralizes build/version metadata so API endpoints (/health, etc.) can
return a single concise object. Keeps runtime fast and resilient: any
failure is caught and converted into a minimal fallback record.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any, Dict
import os
import json
import platform
from pathlib import Path

# Cheap cache (module-level) to avoid repeated filesystem hits
_cached: Dict[str, Any] | None = None

@dataclass
class BuildVersionRecord:
    version: str
    profile: str
    python: str
    platform: str
    git_commit: str | None = None
    git_dirty: bool | None = None

    def to_dict(self) -> Dict[str, Any]:  # explicit for clarity
        return asdict(self)


def _read_version_file() -> str:
    for candidate in ["VERSION", "version.txt"]:
        p = Path(candidate)
        if p.exists():
            try:
                return p.read_text(encoding="utf-8").strip()
            except Exception:
                pass
    return os.getenv("AURORA_VERSION", "unknown")


def _git_meta() -> tuple[str | None, bool | None]:
    try:
        head = Path(".git/HEAD")
        if not head.exists():
            return None, None
        ref_line = head.read_text(encoding="utf-8").strip()
        if ref_line.startswith("ref:"):
            ref_path = Path(".git") / ref_line.split(" ", 1)[1]
            if ref_path.exists():
                commit = ref_path.read_text(encoding="utf-8").strip()[:12]
            else:
                commit = None
        else:
            commit = ref_line[:12]
        # dirty check (quick): any file in .git/index newer than commit? Simplify: look for environment flag
        dirty_flag = os.getenv("AURORA_GIT_DIRTY")
        dirty = dirty_flag.lower() == "true" if isinstance(dirty_flag, str) else None
        return commit, dirty
    except Exception:
        return None, None


def build_version_record(order_profile: str | None = None) -> Dict[str, Any]:
    global _cached
    if _cached is not None and order_profile is not None:
        # reuse but update profile if different
        if _cached.get("profile") != order_profile:
            _cached["profile"] = order_profile
        return _cached

    version = _read_version_file()
    commit, dirty = _git_meta()
    record = BuildVersionRecord(
        version=version,
        profile=order_profile or os.getenv("PRETRADE_ORDER_PROFILE", "unknown"),
        python=platform.python_version(),
        platform=f"{platform.system()}-{platform.machine()}",
        git_commit=commit,
        git_dirty=dirty,
    ).to_dict()
    _cached = record
    return record

if __name__ == "__main__":  # manual debug helper
    print(json.dumps(build_version_record("er_before_slip"), indent=2))
