#!/usr/bin/env python3
"""
Repository Cleanup Script for Aurora Step 3.5
==============================================

Handles PR-cleanup tasks:
1. Remove duplicate files in repo/
2. Rename exchange/config.py → exchange_config.py
3. Unify risk.manager
4. Remove empty stubs (core/regime/hmm.py, core/sizing/portfolio.py, duplicate scripts)
5. Run smoke tests after cleanup

Usage:
    python tools/repo_cleanup.py --dry-run    # Preview changes
    python tools/repo_cleanup.py --execute    # Execute cleanup
"""

import os
import shutil
import argparse
from pathlib import Path
from typing import List, Dict, Set
import subprocess
import sys


class RepoCleanup:
    """Repository cleanup manager"""

    def __init__(self, repo_root: Path, dry_run: bool = True):
        self.repo_root = repo_root
        self.dry_run = dry_run
        self.changes_made = []

    def log_change(self, action: str, description: str):
        """Log a change for reporting"""
        change = f"{action}: {description}"
        self.changes_made.append(change)
        print(f"{'[DRY RUN] ' if self.dry_run else ''}{change}")

    def remove_duplicate_files(self):
        """Remove duplicate files in repo/ directory"""
        repo_dir = self.repo_root / "repo"

        if not repo_dir.exists():
            return

        # Find all files and identify duplicates by content
        file_hashes = {}
        duplicates = []

        for file_path in repo_dir.rglob("*"):
            if file_path.is_file():
                try:
                    with open(file_path, 'rb') as f:
                        file_hash = hash(f.read())

                    if file_hash in file_hashes:
                        duplicates.append((file_path, file_hashes[file_hash]))
                    else:
                        file_hashes[file_hash] = file_path
                except Exception as e:
                    print(f"Warning: Could not hash {file_path}: {e}")

        # Remove duplicates (keep first occurrence)
        for duplicate, original in duplicates:
            self.log_change("REMOVE", f"Duplicate file {duplicate} (original: {original})")
            if not self.dry_run:
                duplicate.unlink()

    def rename_exchange_config(self):
        """Rename exchange/config.py → exchange_config.py"""
        old_path = self.repo_root / "exchange" / "config.py"
        new_path = self.repo_root / "exchange" / "exchange_config.py"

        if old_path.exists():
            self.log_change("RENAME", f"{old_path} → {new_path}")
            if not self.dry_run:
                old_path.rename(new_path)

                # Update imports in Python files
                self._update_imports("exchange.config", "exchange.exchange_config")

    def unify_risk_manager(self):
        """Unify risk.manager implementations"""
        risk_dir = self.repo_root / "risk"

        if not risk_dir.exists():
            return

        # Find all risk manager files
        risk_managers = list(risk_dir.glob("*manager*"))

        if len(risk_managers) <= 1:
            return

        # Keep the most complete implementation
        primary_manager = None
        max_size = 0

        for manager in risk_managers:
            size = manager.stat().st_size
            if size > max_size:
                max_size = size
                primary_manager = manager

        # Remove others
        for manager in risk_managers:
            if manager != primary_manager:
                self.log_change("REMOVE", f"Duplicate risk manager {manager}")
                if not self.dry_run:
                    manager.unlink()

        # Rename to standard name
        if primary_manager:
            standard_name = risk_dir / "risk_manager.py"
            if primary_manager != standard_name:
                self.log_change("RENAME", f"{primary_manager} → {standard_name}")
                if not self.dry_run:
                    primary_manager.rename(standard_name)

    def remove_empty_stubs(self):
        """Remove empty or minimal stub files"""
        stub_files = [
            "core/regime/hmm.py",
            "core/sizing/portfolio.py",
        ]

        # Also find other potential stubs
        stub_patterns = [
            "core/**/*.py",
            "skalp_bot/**/*.py",
            "api/**/*.py"
        ]

        for pattern in stub_patterns:
            for file_path in self.repo_root.glob(pattern):
                if file_path.is_file():
                    try:
                        with open(file_path, 'r', encoding='utf-8') as f:
                            content = f.read().strip()

                        # Check if it's a stub (very short, mostly comments/imports)
                        lines = content.split('\n')
                        code_lines = [line for line in lines if line.strip() and not line.strip().startswith('#')]

                        if len(code_lines) <= 3:  # Very few actual code lines
                            stub_files.append(str(file_path.relative_to(self.repo_root)))
                    except Exception:
                        pass

        # Remove identified stubs
        for stub_file in stub_files:
            stub_path = self.repo_root / stub_file
            if stub_path.exists():
                self.log_change("REMOVE", f"Empty stub {stub_file}")
                if not self.dry_run:
                    stub_path.unlink()

    def remove_duplicate_scripts(self):
        """Remove duplicate scripts in scripts/ directory"""
        scripts_dir = self.repo_root / "scripts"

        if not scripts_dir.exists():
            return

        # Find duplicate scripts by name and content
        script_files = {}
        duplicates = []

        for script in scripts_dir.glob("*"):
            if script.is_file():
                script_name = script.name
                try:
                    with open(script, 'rb') as f:
                        content_hash = hash(f.read())

                    key = (script_name, content_hash)
                    if key in script_files:
                        duplicates.append(script)
                    else:
                        script_files[key] = script
                except Exception as e:
                    print(f"Warning: Could not process {script}: {e}")

        # Remove duplicates
        for duplicate in duplicates:
            self.log_change("REMOVE", f"Duplicate script {duplicate}")
            if not self.dry_run:
                duplicate.unlink()

    def _update_imports(self, old_import: str, new_import: str):
        """Update import statements in Python files"""
        for py_file in self.repo_root.glob("**/*.py"):
            try:
                with open(py_file, 'r', encoding='utf-8') as f:
                    content = f.read()

                if old_import in content:
                    new_content = content.replace(old_import, new_import)
                    if not self.dry_run:
                        with open(py_file, 'w', encoding='utf-8') as f:
                            f.write(new_content)
                    self.log_change("UPDATE", f"Import in {py_file}")
            except Exception as e:
                print(f"Warning: Could not update imports in {py_file}: {e}")

    def run_smoke_tests(self):
        """Run smoke tests after cleanup"""
        self.log_change("TEST", "Running smoke tests...")

        if self.dry_run:
            return

        # Run basic import tests
        test_commands = [
            ["python", "-c", "import core.execution.execution_router_v1; print('Execution router OK')"],
            ["python", "-c", "import core.tca.tca_analyzer; print('TCA analyzer OK')"],
            ["python", "-c", "import common.events; print('Events OK')"],
            ["python", "-c", "import core.canary.canary_system; print('Canary system OK')"],
        ]

        for cmd in test_commands:
            try:
                result = subprocess.run(cmd, cwd=self.repo_root, capture_output=True, text=True, timeout=10)
                if result.returncode == 0:
                    print(f"✓ {cmd[-1]}")
                else:
                    print(f"✗ {cmd[-1]}: {result.stderr}")
            except Exception as e:
                print(f"✗ {cmd[-1]}: {e}")

    def execute_cleanup(self):
        """Execute all cleanup operations"""
        print("Starting repository cleanup...")

        self.remove_duplicate_files()
        self.rename_exchange_config()
        self.unify_risk_manager()
        self.remove_empty_stubs()
        self.remove_duplicate_scripts()

        print(f"\nCleanup complete. {len(self.changes_made)} changes made.")

        if not self.dry_run:
            print("\nRunning smoke tests...")
            self.run_smoke_tests()

    def get_summary(self) -> Dict:
        """Get cleanup summary"""
        return {
            "changes_made": len(self.changes_made),
            "changes_list": self.changes_made,
            "dry_run": self.dry_run
        }


def main():
    parser = argparse.ArgumentParser(description="Repository cleanup for Aurora")
    parser.add_argument("--dry-run", action="store_true", help="Preview changes without executing")
    parser.add_argument("--execute", action="store_true", help="Execute cleanup operations")

    args = parser.parse_args()

    if not args.dry_run and not args.execute:
        print("Please specify --dry-run or --execute")
        sys.exit(1)

    dry_run = not args.execute

    repo_root = Path(__file__).parent.parent
    cleanup = RepoCleanup(repo_root, dry_run=dry_run)

    cleanup.execute_cleanup()

    summary = cleanup.get_summary()
    print(f"\nSummary: {summary['changes_made']} changes {'would be' if dry_run else ''} made")


if __name__ == "__main__":
    main()