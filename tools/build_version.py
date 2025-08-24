from __future__ import annotations

import os
import subprocess
from datetime import datetime


def get_git_info() -> dict:
    def _run(cmd: list[str]) -> str:
        try:
            return subprocess.check_output(cmd, stderr=subprocess.DEVNULL).decode().strip()
        except Exception:
            return "unknown"
    sha = _run(["git", "rev-parse", "HEAD"])[:7]
    branch = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"]) or os.getenv('GIT_BRANCH', 'unknown')
    return {"sha": sha or "unknown", "branch": branch or "unknown"}


def build_version_record(order_profile: str) -> dict:
    git = get_git_info()
    return {
        "sha": git["sha"],
        "branch": git["branch"],
        "build_ts": datetime.utcnow().isoformat() + "Z",
        "order_profile": order_profile,
    }
