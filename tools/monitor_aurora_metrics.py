#!/usr/bin/env python3
"""
P11.Monitor - Real-time Aurora API Metrics Monitor
Continuously monitors /metrics endpoint for IDEM patterns, exchange retries, and XAI events
"""

import json
import os
import signal
import sys
import time
from datetime import datetime
from typing import Dict, Set

import requests
from dotenv import load_dotenv


class AuroraMetricsMonitor:
    """Real-time Aurora API metrics monitor"""

    def __init__(self, api_url: str = "http://127.0.0.1:8000", poll_interval: int = 10):
        load_dotenv()
        self.api_url = api_url
        self.poll_interval = poll_interval
        self.ops_token = os.getenv("AURORA_OPS_TOKEN")
        self.running = True
        self.previous_metrics = {}

        # Setup signal handlers for graceful shutdown
        signal.signal(signal.SIGINT, self._handle_shutdown)
        signal.signal(signal.SIGTERM, self._handle_shutdown)

    def _handle_shutdown(self, signum, frame):
        """Handle shutdown signals"""
        print(f"\n🛑 Received signal {signum}, shutting down gracefully...")
        self.running = False

    def get_metrics(self) -> Dict[str, float]:
        """Fetch current metrics from Aurora API"""
        try:
            headers = {"X-OPS-TOKEN": self.ops_token} if self.ops_token else {}
            response = requests.get(
                f"{self.api_url}/metrics", headers=headers, timeout=5
            )

            if response.status_code != 200:
                print(f"❌ Metrics API error: {response.status_code}")
                return {}

            # Parse Prometheus metrics
            metrics = {}
            for line in response.text.split("\n"):
                line = line.strip()
                if line and not line.startswith("#"):
                    parts = line.split(" ")
                    if len(parts) >= 2:
                        metric_name = parts[0]
                        try:
                            metric_value = float(parts[1])
                            metrics[metric_name] = metric_value
                        except ValueError:
                            continue

            return metrics

        except requests.RequestException as e:
            print(f"❌ Failed to fetch metrics: {e}")
            return {}

    def get_health(self) -> Dict:
        """Fetch health status from Aurora API"""
        try:
            headers = {"X-OPS-TOKEN": self.ops_token} if self.ops_token else {}
            response = requests.get(
                f"{self.api_url}/health", headers=headers, timeout=5
            )

            if response.status_code == 200:
                return response.json()
            else:
                return {"status": "error", "code": response.status_code}

        except requests.RequestException as e:
            return {"status": "unreachable", "error": str(e)}

    def calculate_deltas(self, current: Dict[str, float]) -> Dict[str, float]:
        """Calculate metric deltas since last poll"""
        deltas = {}
        for metric, value in current.items():
            if metric in self.previous_metrics:
                delta = value - self.previous_metrics[metric]
                if delta != 0:  # Only report non-zero deltas
                    deltas[metric] = delta
            else:
                deltas[metric] = value  # First time we see this metric

        return deltas

    def print_status_line(
        self, metrics: Dict[str, float], deltas: Dict[str, float], health: Dict
    ):
        """Print current status line"""
        timestamp = datetime.now().strftime("%H:%M:%S")
        status = health.get("status", "unknown")

        # Key IDEM metrics
        idem_check = metrics.get("aurora_idem_check_total", 0)
        idem_update = metrics.get("aurora_idem_update_total", 0)
        idem_duplicate = metrics.get("aurora_idem_duplicate_submit_total", 0)

        # Exchange metrics
        exchange_retry = sum(v for k, v in metrics.items() if "exchange_retry" in k)

        # Pretrade metrics
        pretrade_total = sum(
            v for k, v in metrics.items() if "pretrade" in k and "total" in k
        )

        print(
            f"[{timestamp}] 🚀 {status.upper()} | "
            f"IDEM: ✓{int(idem_check)} ↻{int(idem_update)} ⚠{int(idem_duplicate)} | "
            f"Retry: {int(exchange_retry)} | "
            f"Pretrade: {int(pretrade_total)}"
        )

        # Print significant deltas
        if deltas:
            delta_items = []
            for metric, delta in deltas.items():
                if "aurora_idem" in metric:
                    delta_items.append(f"  🔒 {metric}: +{int(delta)}")
                elif "exchange_retry" in metric:
                    delta_items.append(f"  🔄 {metric}: +{int(delta)}")
                elif "pretrade" in metric:
                    delta_items.append(f"  🛡️ {metric}: +{int(delta)}")

            if delta_items:
                for item in delta_items[:5]:  # Limit to 5 most important
                    print(item)

    def monitor_detailed(self):
        """Detailed monitoring mode with full metric breakdown"""
        print("🔍 DETAILED MONITORING MODE")
        print("=" * 60)

        while self.running:
            try:
                metrics = self.get_metrics()
                health = self.get_health()

                if not metrics:
                    time.sleep(self.poll_interval)
                    continue

                timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                print(f"\n📊 [{timestamp}] Aurora Metrics Snapshot")
                print("-" * 50)

                # Group metrics by category
                idem_metrics = {k: v for k, v in metrics.items() if "aurora_idem" in k}
                exchange_metrics = {k: v for k, v in metrics.items() if "exchange" in k}
                pretrade_metrics = {k: v for k, v in metrics.items() if "pretrade" in k}

                if idem_metrics:
                    print("🔒 IDEMPOTENCY:")
                    for metric, value in idem_metrics.items():
                        print(f"   {metric}: {int(value)}")

                if exchange_metrics:
                    print("🔄 EXCHANGE:")
                    for metric, value in exchange_metrics.items():
                        print(f"   {metric}: {int(value)}")

                if pretrade_metrics:
                    print("🛡️ PRETRADE:")
                    for metric, value in pretrade_metrics.items():
                        print(f"   {metric}: {int(value)}")

                print(f"💚 API Health: {health.get('status', 'unknown')}")

                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Monitor error: {e}")
                time.sleep(self.poll_interval)

    def monitor_compact(self):
        """Compact monitoring mode with status line updates"""
        print("🎯 COMPACT MONITORING MODE")
        print("=" * 60)
        print("Monitoring IDEM patterns, exchange retries, and pretrade metrics...")
        print("Press Ctrl+C to stop")
        print()

        while self.running:
            try:
                metrics = self.get_metrics()
                health = self.get_health()

                if metrics:
                    deltas = self.calculate_deltas(metrics)
                    self.print_status_line(metrics, deltas, health)
                    self.previous_metrics = metrics.copy()
                else:
                    print(
                        f"[{datetime.now().strftime('%H:%M:%S')}] ❌ No metrics available"
                    )

                time.sleep(self.poll_interval)

            except KeyboardInterrupt:
                break
            except Exception as e:
                print(f"❌ Monitor error: {e}")
                time.sleep(self.poll_interval)

    def run(self, mode: str = "compact"):
        """Run the monitor"""
        print(f"🚀 Starting Aurora Metrics Monitor")
        print(f"   API: {self.api_url}")
        print(f"   Poll interval: {self.poll_interval}s")
        print(f"   Mode: {mode}")
        print()

        try:
            if mode == "detailed":
                self.monitor_detailed()
            else:
                self.monitor_compact()
        finally:
            print("\n✅ Monitor stopped gracefully")


def main():
    import argparse

    parser = argparse.ArgumentParser(description="Real-time Aurora API metrics monitor")
    parser.add_argument(
        "--api-url", default="http://127.0.0.1:8000", help="Aurora API URL"
    )
    parser.add_argument(
        "--interval", type=int, default=10, help="Poll interval in seconds"
    )
    parser.add_argument(
        "--mode",
        choices=["compact", "detailed"],
        default="compact",
        help="Monitoring mode",
    )

    args = parser.parse_args()

    monitor = AuroraMetricsMonitor(api_url=args.api_url, poll_interval=args.interval)

    monitor.run(mode=args.mode)


if __name__ == "__main__":
    main()
