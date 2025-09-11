#!/usr/bin/env python3
"""
P13.Artifacts - Comprehensive Canary Artifacts Collection
Collects and preserves all canary artifacts for analysis and auditing
"""

import json
import os
import shutil
import zipfile
from datetime import datetime
from pathlib import Path
from typing import Dict, List

import requests
from dotenv import load_dotenv


class CanaryArtifactsCollector:
    """Comprehensive canary artifacts collector"""

    def __init__(self, session_dir: str = "logs/production_testnet_session"):
        load_dotenv()
        self.session_dir = Path(session_dir)
        self.artifacts_dir = Path("artifacts")
        self.ops_token = os.getenv("AURORA_OPS_TOKEN")
        self.api_url = "http://127.0.0.1:8000"

        # Create artifacts directory
        self.artifacts_dir.mkdir(exist_ok=True)

        # Generate collection timestamp
        self.timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.collection_dir = self.artifacts_dir / f"canary_collection_{self.timestamp}"
        self.collection_dir.mkdir(exist_ok=True)

        print(f"📦 Artifacts Collector initialized")
        print(f"   Session: {self.session_dir}")
        print(f"   Collection: {self.collection_dir}")

    def collect_session_logs(self):
        """Collect all session log files"""
        logs_dest = self.collection_dir / "logs"
        logs_dest.mkdir(exist_ok=True)

        if not self.session_dir.exists():
            print(f"⚠️ Session directory not found: {self.session_dir}")
            return

        print("📋 Collecting session logs...")
        copied = 0

        for log_file in self.session_dir.glob("*.jsonl*"):
            dest_file = logs_dest / log_file.name
            shutil.copy2(log_file, dest_file)
            print(f"   ✓ {log_file.name} ({log_file.stat().st_size} bytes)")
            copied += 1

        print(f"✅ Collected {copied} log files")

    def collect_current_metrics(self):
        """Collect current API metrics snapshot"""
        print("📊 Collecting metrics snapshot...")

        try:
            headers = {"X-OPS-TOKEN": self.ops_token} if self.ops_token else {}

            # Health endpoint
            health_resp = requests.get(
                f"{self.api_url}/health", headers=headers, timeout=5
            )
            if health_resp.status_code == 200:
                health_file = self.collection_dir / "api_health.json"
                with open(health_file, "w") as f:
                    json.dump(health_resp.json(), f, indent=2)
                print("   ✓ API health captured")

            # Metrics endpoint
            metrics_resp = requests.get(
                f"{self.api_url}/metrics", headers=headers, timeout=5
            )
            if metrics_resp.status_code == 200:
                metrics_file = self.collection_dir / "api_metrics.txt"
                with open(metrics_file, "w") as f:
                    f.write(metrics_resp.text)
                print("   ✓ API metrics captured")

        except requests.RequestException as e:
            print(f"   ⚠️ Failed to collect API data: {e}")

    def collect_config_files(self):
        """Collect relevant configuration files"""
        print("⚙️ Collecting configuration files...")

        config_dest = self.collection_dir / "configs"
        config_dest.mkdir(exist_ok=True)

        config_files = [
            ".env",
            ".env.testnet.example",
            "configs/exchanges/binance_testnet_futures.json",
            "pytest.ini",
            ".coveragerc",
        ]

        copied = 0
        for config_file in config_files:
            src_path = Path(config_file)
            if src_path.exists():
                # Create subdirectories if needed
                dest_path = config_dest / config_file
                dest_path.parent.mkdir(parents=True, exist_ok=True)

                # Mask sensitive data in .env files
                if src_path.name.startswith(".env") and not src_path.name.endswith(
                    ".example"
                ):
                    self._copy_env_masked(src_path, dest_path)
                else:
                    shutil.copy2(src_path, dest_path)

                print(f"   ✓ {config_file}")
                copied += 1
            else:
                print(f"   ⚠️ Not found: {config_file}")

        print(f"✅ Collected {copied} configuration files")

    def _copy_env_masked(self, src: Path, dest: Path):
        """Copy .env file with masked sensitive values"""
        with open(src, "r") as f:
            lines = f.readlines()

        masked_lines = []
        for line in lines:
            if "=" in line and not line.startswith("#"):
                key, value = line.split("=", 1)
                key = key.strip()
                value = value.strip()

                # Mask sensitive keys
                if any(
                    sensitive in key.upper()
                    for sensitive in ["KEY", "SECRET", "TOKEN", "PASSWORD"]
                ):
                    if len(value) > 8:
                        masked_value = value[:4] + "*" * (len(value) - 8) + value[-4:]
                    else:
                        masked_value = "*" * len(value)
                    masked_lines.append(f"{key}={masked_value}\n")
                else:
                    masked_lines.append(line)
            else:
                masked_lines.append(line)

        with open(dest, "w") as f:
            f.writelines(masked_lines)

    def collect_coverage_reports(self):
        """Collect coverage reports if available"""
        print("📈 Collecting coverage reports...")

        coverage_dest = self.collection_dir / "coverage"
        coverage_dest.mkdir(exist_ok=True)

        coverage_files = [
            "coverage.xml",
            "reports/coverage.xml",
            "reports/coverage_html",
            ".coverage",
        ]

        copied = 0
        for coverage_file in coverage_files:
            src_path = Path(coverage_file)
            if src_path.exists():
                if src_path.is_dir():
                    dest_path = coverage_dest / src_path.name
                    shutil.copytree(src_path, dest_path, dirs_exist_ok=True)
                    print(f"   ✓ {coverage_file}/ (directory)")
                else:
                    dest_path = coverage_dest / src_path.name
                    shutil.copy2(src_path, dest_path)
                    print(f"   ✓ {coverage_file} ({src_path.stat().st_size} bytes)")
                copied += 1

        print(f"✅ Collected {copied} coverage artifacts")

    def generate_collection_manifest(self):
        """Generate manifest of collected artifacts"""
        print("📄 Generating collection manifest...")

        manifest = {
            "collection_timestamp": self.timestamp,
            "collection_date": datetime.now().isoformat(),
            "session_dir": str(self.session_dir),
            "artifacts": [],
            "summary": {},
        }

        # Walk through collected files
        total_size = 0
        file_count = 0

        for file_path in self.collection_dir.rglob("*"):
            if file_path.is_file() and file_path.name != "manifest.json":
                rel_path = file_path.relative_to(self.collection_dir)
                size = file_path.stat().st_size

                manifest["artifacts"].append(
                    {
                        "path": str(rel_path),
                        "size_bytes": size,
                        "modified": datetime.fromtimestamp(
                            file_path.stat().st_mtime
                        ).isoformat(),
                    }
                )

                total_size += size
                file_count += 1

        manifest["summary"] = {
            "total_files": file_count,
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
        }

        # Save manifest
        manifest_file = self.collection_dir / "manifest.json"
        with open(manifest_file, "w") as f:
            json.dump(manifest, f, indent=2)

        print(
            f"✅ Manifest created: {file_count} files, {manifest['summary']['total_size_mb']} MB"
        )

    def create_collection_archive(self) -> Path:
        """Create ZIP archive of collection"""
        print("🗜️ Creating collection archive...")

        archive_name = f"canary_artifacts_{self.timestamp}.zip"
        archive_path = self.artifacts_dir / archive_name

        with zipfile.ZipFile(archive_path, "w", zipfile.ZIP_DEFLATED) as zipf:
            for file_path in self.collection_dir.rglob("*"):
                if file_path.is_file():
                    arcname = file_path.relative_to(self.collection_dir)
                    zipf.write(file_path, arcname)

        archive_size_mb = round(archive_path.stat().st_size / (1024 * 1024), 2)
        print(f"✅ Archive created: {archive_name} ({archive_size_mb} MB)")

        return archive_path

    def analyze_session_summary(self):
        """Generate session analysis summary"""
        print("🔍 Analyzing session summary...")

        summary = {
            "analysis_timestamp": datetime.now().isoformat(),
            "session_duration": "unknown",
            "events_summary": {},
            "orders_summary": {},
            "idem_summary": {},
        }

        # Analyze main events log
        events_file = self.session_dir / "aurora_events.jsonl"
        if events_file.exists():
            with open(events_file, "r") as f:
                lines = f.readlines()

            total_events = len(lines)
            event_types = {}

            # Sample first and last events for duration
            try:
                first_event = json.loads(lines[0])
                last_event = json.loads(lines[-1])

                first_ts = first_event.get("ts", 0) / 1000
                last_ts = last_event.get("ts", 0) / 1000
                duration_seconds = last_ts - first_ts
                duration_minutes = duration_seconds / 60

                summary["session_duration"] = f"{duration_minutes:.1f} minutes"
                summary["start_time"] = datetime.fromtimestamp(first_ts).isoformat()
                summary["end_time"] = datetime.fromtimestamp(last_ts).isoformat()

            except (json.JSONDecodeError, IndexError, KeyError):
                pass

            # Count event types (sample first 1000 for performance)
            for line in lines[:1000]:
                try:
                    event = json.loads(line)
                    event_code = event.get("event_code") or event.get("type", "unknown")
                    event_types[event_code] = event_types.get(event_code, 0) + 1
                except json.JSONDecodeError:
                    continue

            summary["events_summary"] = {
                "total_events": total_events,
                "event_types": dict(
                    sorted(event_types.items(), key=lambda x: x[1], reverse=True)
                ),
            }

        # Analyze orders
        for order_type in ["success", "denied", "failed"]:
            orders_file = self.session_dir / f"orders_{order_type}.jsonl"
            if orders_file.exists():
                with open(orders_file, "r") as f:
                    count = len(f.readlines())
                summary["orders_summary"][order_type] = count

        # Save summary
        summary_file = self.collection_dir / "session_analysis.json"
        with open(summary_file, "w") as f:
            json.dump(summary, f, indent=2)

        print(f"✅ Session analysis completed")
        return summary

    def collect_all(self, create_archive: bool = True):
        """Collect all canary artifacts"""
        print(f"🚀 Starting comprehensive canary artifacts collection")
        print("=" * 60)

        try:
            # Collect all artifact types
            self.collect_session_logs()
            self.collect_current_metrics()
            self.collect_config_files()
            self.collect_coverage_reports()

            # Generate analysis and manifest
            summary = self.analyze_session_summary()
            self.generate_collection_manifest()

            # Create archive if requested
            archive_path = None
            if create_archive:
                archive_path = self.create_collection_archive()

            print("\n🎉 ARTIFACTS COLLECTION COMPLETED")
            print("=" * 60)
            print(f"📁 Collection directory: {self.collection_dir}")
            if archive_path:
                print(f"📦 Collection archive: {archive_path}")
            print(f"⏱️ Session duration: {summary.get('session_duration', 'unknown')}")
            print(
                f"📊 Total events: {summary.get('events_summary', {}).get('total_events', 'unknown')}"
            )

            orders = summary.get("orders_summary", {})
            if orders:
                print(
                    f"📋 Orders: ✅{orders.get('success', 0)} ❌{orders.get('denied', 0)} ⚠️{orders.get('failed', 0)}"
                )

            return self.collection_dir, archive_path

        except Exception as e:
            print(f"❌ Collection failed: {e}")
            raise


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Collect canary artifacts")
    parser.add_argument(
        "--session-dir",
        default="logs/production_testnet_session",
        help="Session logs directory",
    )
    parser.add_argument(
        "--no-archive", action="store_true", help="Skip creating ZIP archive"
    )

    args = parser.parse_args()

    collector = CanaryArtifactsCollector(args.session_dir)
    collector.collect_all(create_archive=not args.no_archive)


if __name__ == "__main__":
    main()
