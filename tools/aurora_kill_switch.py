#!/usr/bin/env python3
"""
P12.Kill-Switch - Automatic Kill-Switch for Aurora Runner
Implements real-time KPI monitoring with automatic runner termination
"""

import os
import signal
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Dict, List, Optional

import psutil
import requests
from dotenv import load_dotenv


@dataclass
class KillSwitchThresholds:
    """Kill-switch activation thresholds"""

    max_consecutive_errors: int = 5
    max_error_rate_per_minute: float = 10.0
    max_latency_ms: float = 2000.0
    min_health_checks_failed: int = 3
    max_deny_rate: float = 0.95
    max_duplicate_rate: float = 0.50
    monitoring_window_minutes: int = 5


class AuroraKillSwitch:
    """Automatic kill-switch for Aurora runner with real-time monitoring"""

    def __init__(self, thresholds: KillSwitchThresholds = None):
        load_dotenv()
        self.thresholds = thresholds or KillSwitchThresholds()
        self.api_url = "http://127.0.0.1:8000"
        self.ops_token = os.getenv("AURORA_OPS_TOKEN")

        # State tracking
        self.consecutive_errors = 0
        self.error_timestamps = []
        self.health_check_failures = 0
        self.last_metrics = {}
        self.kill_switch_active = False

        print(f"🛡️ Aurora Kill-Switch initialized")
        print(f"   Thresholds: {self.thresholds}")

    def get_runner_processes(self) -> List[psutil.Process]:
        """Find running Aurora runner processes"""
        processes = []
        for proc in psutil.process_iter(["pid", "name", "cmdline"]):
            try:
                cmdline = " ".join(proc.info["cmdline"] or [])
                if "run_live_aurora" in cmdline or "skalp_bot.runner" in cmdline:
                    processes.append(proc)
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue
        return processes

    def terminate_runner(self, reason: str) -> bool:
        """Terminate Aurora runner processes"""
        processes = self.get_runner_processes()

        if not processes:
            print("⚠️ No Aurora runner processes found")
            return False

        print(f"🚨 KILL-SWITCH ACTIVATED: {reason}")
        print(f"📋 Found {len(processes)} runner process(es) to terminate")

        terminated = []
        for proc in processes:
            try:
                print(f"   Terminating PID {proc.pid}: {' '.join(proc.cmdline())}")
                proc.terminate()
                terminated.append(proc.pid)
            except (psutil.NoSuchProcess, psutil.AccessDenied) as e:
                print(f"   Failed to terminate PID {proc.pid}: {e}")

        # Wait for graceful shutdown
        time.sleep(3)

        # Force kill if needed
        for proc in processes:
            try:
                if proc.is_running():
                    print(f"   Force killing PID {proc.pid}")
                    proc.kill()
            except psutil.NoSuchProcess:
                pass

        print(f"✅ Kill-switch executed: {len(terminated)} processes terminated")
        return len(terminated) > 0

    def check_api_health(self) -> Dict:
        """Check Aurora API health"""
        try:
            headers = {"X-OPS-TOKEN": self.ops_token} if self.ops_token else {}
            response = requests.get(
                f"{self.api_url}/health", headers=headers, timeout=5
            )

            if response.status_code == 200:
                return {"status": "healthy", "data": response.json()}
            else:
                return {"status": "unhealthy", "code": response.status_code}

        except requests.RequestException as e:
            return {"status": "unreachable", "error": str(e)}

    def get_metrics(self) -> Dict[str, float]:
        """Get current metrics from Aurora API"""
        try:
            headers = {"X-OPS-TOKEN": self.ops_token} if self.ops_token else {}
            response = requests.get(
                f"{self.api_url}/metrics", headers=headers, timeout=5
            )

            if response.status_code != 200:
                return {}

            metrics = {}
            for line in response.text.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(" ")
                    if len(parts) >= 2:
                        try:
                            metrics[parts[0]] = float(parts[1])
                        except ValueError:
                            continue
            return metrics

        except requests.RequestException:
            return {}

    def analyze_metrics(self, current_metrics: Dict[str, float]) -> List[str]:
        """Analyze metrics for kill-switch conditions"""
        issues = []

        # Check for excessive duplicate submissions
        duplicate_total = current_metrics.get("aurora_idem_duplicate_submit_total", 0)
        check_total = current_metrics.get(
            "aurora_idem_check_total", 1
        )  # Avoid division by zero

        if (
            check_total > 0
            and duplicate_total / check_total > self.thresholds.max_duplicate_rate
        ):
            issues.append(
                f"High duplicate rate: {duplicate_total/check_total:.2f} > {self.thresholds.max_duplicate_rate}"
            )

        # Check for metric deltas indicating problems
        if self.last_metrics:
            # Look for concerning trends
            error_delta = current_metrics.get(
                "aurora_errors_total", 0
            ) - self.last_metrics.get("aurora_errors_total", 0)
            if error_delta > 5:  # More than 5 new errors since last check
                issues.append(f"Error spike: +{error_delta} errors")

        return issues

    def should_activate_kill_switch(self) -> Optional[str]:
        """Check if kill-switch should be activated"""

        # Check API health
        health = self.check_api_health()
        if health["status"] != "healthy":
            self.health_check_failures += 1
            if self.health_check_failures >= self.thresholds.min_health_checks_failed:
                return f"API health failures: {self.health_check_failures} consecutive failures"
        else:
            self.health_check_failures = 0  # Reset on successful health check

        # Check metrics
        metrics = self.get_metrics()
        if not metrics:
            self.consecutive_errors += 1
            if self.consecutive_errors >= self.thresholds.max_consecutive_errors:
                return f"Metrics unavailable: {self.consecutive_errors} consecutive failures"
        else:
            self.consecutive_errors = 0  # Reset on successful metrics fetch

            # Analyze metrics for issues
            issues = self.analyze_metrics(metrics)
            if issues:
                return f"Metric thresholds exceeded: {', '.join(issues)}"

            self.last_metrics = metrics

        # Check error rate
        now = datetime.now()
        self.error_timestamps = [
            ts for ts in self.error_timestamps if now - ts < timedelta(minutes=1)
        ]

        if len(self.error_timestamps) > self.thresholds.max_error_rate_per_minute:
            return f"High error rate: {len(self.error_timestamps)} errors/minute > {self.thresholds.max_error_rate_per_minute}"

        return None

    def monitor_with_kill_switch(self, check_interval: int = 10):
        """Run monitoring with automatic kill-switch"""
        print(f"🎯 Starting kill-switch monitoring (interval: {check_interval}s)")
        print("=" * 60)

        while not self.kill_switch_active:
            try:
                timestamp = datetime.now().strftime("%H:%M:%S")

                # Check if kill-switch should be activated
                kill_reason = self.should_activate_kill_switch()

                if kill_reason:
                    self.kill_switch_active = True
                    success = self.terminate_runner(kill_reason)

                    if success:
                        print(
                            f"[{timestamp}] 🛑 KILL-SWITCH: Runner terminated due to: {kill_reason}"
                        )
                        return True
                    else:
                        print(
                            f"[{timestamp}] ⚠️ KILL-SWITCH: Failed to terminate runner"
                        )
                        return False
                else:
                    # Print status
                    health = self.check_api_health()
                    metrics = self.get_metrics()

                    idem_check = metrics.get("aurora_idem_check_total", 0)
                    idem_duplicate = metrics.get(
                        "aurora_idem_duplicate_submit_total", 0
                    )

                    status = health.get("status", "unknown")
                    print(
                        f"[{timestamp}] ✅ Monitoring: {status.upper()} | "
                        f"Health failures: {self.health_check_failures} | "
                        f"IDEM: ✓{int(idem_check)} ⚠{int(idem_duplicate)} | "
                        f"Consecutive errors: {self.consecutive_errors}"
                    )

                time.sleep(check_interval)

            except KeyboardInterrupt:
                print(f"\n🛑 Kill-switch monitoring stopped by user")
                return False
            except Exception as e:
                print(f"❌ Kill-switch error: {e}")
                self.error_timestamps.append(datetime.now())
                time.sleep(check_interval)

        return False

    def manual_kill(self, reason: str = "Manual termination"):
        """Manually activate kill-switch"""
        return self.terminate_runner(reason)


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Aurora Kill-Switch Monitor")
    parser.add_argument(
        "--interval", type=int, default=10, help="Check interval in seconds"
    )
    parser.add_argument(
        "--max-errors", type=int, default=5, help="Max consecutive errors before kill"
    )
    parser.add_argument(
        "--max-health-failures", type=int, default=3, help="Max health check failures"
    )
    parser.add_argument(
        "--manual-kill", action="store_true", help="Manually kill runner"
    )

    args = parser.parse_args()

    thresholds = KillSwitchThresholds(
        max_consecutive_errors=args.max_errors,
        min_health_checks_failed=args.max_health_failures,
    )

    kill_switch = AuroraKillSwitch(thresholds)

    if args.manual_kill:
        success = kill_switch.manual_kill("Manual kill requested")
        exit(0 if success else 1)
    else:
        kill_switch.monitor_with_kill_switch(args.interval)


if __name__ == "__main__":
    main()
