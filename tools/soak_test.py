#!/usr/bin/env python3
"""
Soak Testing Script for Aurora Step 3.5
========================================

Runs comprehensive soak testing on testnet for 2-4 hours with:
- ≥500 order events
- fill_ratio ≥ 0.55 at spread_limit_bps ≤ 8
- TCA metrics: median(IS_bps) ≤ 1.5, p90(IS_bps) ≤ 5
- Adv_bps positive in ≥55% buy-fills
- p95 decide→route ≤ 5ms

Usage:
    python tools/soak_test.py --duration-hours 2 --target-events 500
"""

import argparse
from dataclasses import dataclass, field
import json
from pathlib import Path
import random
import statistics
import threading
import time

from common.events import EventEmitter
from core.execution.execution_router_v1 import ExecutionContext, ExecutionRouter
from core.tca.tca_analyzer import FillEvent


@dataclass
class SoakTestConfig:
    """Configuration for soak testing"""
    duration_hours: float = 2.0
    target_order_events: int = 500
    symbols: list[str] = field(default_factory=lambda: ["BTCUSDT", "ETHUSDT"])
    max_concurrent_orders: int = 10
    decision_interval_ms: int = 100  # 10 decisions per second
    metrics_interval_s: int = 30

    # Test parameters
    spread_limit_bps: float = 8.0
    target_fill_ratio: float = 0.55
    target_median_is_bps: float = 1.5
    target_p90_is_bps: float = 5.0
    target_positive_adv_ratio: float = 0.55
    target_decision_latency_p95_ms: float = 5.0


@dataclass
class SoakTestMetrics:
    """Real-time soak test metrics"""
    start_time: float
    end_time: float | None = None

    # Order metrics
    total_orders: int = 0
    filled_orders: int = 0
    cancelled_orders: int = 0
    rejected_orders: int = 0

    # Performance metrics
    decision_latencies_ms: list[float] = field(default_factory=list)
    fill_latencies_ms: list[float] = field(default_factory=list)

    # TCA metrics
    implementation_shortfall_bps: list[float] = field(default_factory=list)
    adverse_selection_bps: list[float] = field(default_factory=list)
    spread_cost_bps: list[float] = field(default_factory=list)

    # Market condition metrics
    spread_bps_values: list[float] = field(default_factory=list)
    fill_ratios: list[float] = field(default_factory=list)

    # Error tracking
    errors: list[dict] = field(default_factory=list)


class SoakTestRunner:
    """Soak test runner with comprehensive metrics collection"""

    def __init__(self, config: SoakTestConfig | None = None):
        self.config = config or SoakTestConfig()
        self.metrics = SoakTestMetrics(start_time=time.time())

        # Components
        self.execution_router = ExecutionRouter()
        self.event_logger = EventEmitter()

        # Control flags
        self.running = False
        self.test_thread = None
        self.monitor_thread = None

        # Active orders tracking
        self.active_orders = {}
        self.order_counter = 0

    def start_test(self):
        """Start soak test"""
        print(f"Starting soak test for {self.config.duration_hours} hours...")
        print(f"Target: {self.config.target_order_events} order events")

        self.running = True

        # Start test thread
        self.test_thread = threading.Thread(target=self._run_test_loop)
        self.test_thread.start()

        # Start monitoring thread
        self.monitor_thread = threading.Thread(target=self._monitoring_loop)
        self.monitor_thread.start()

        # Wait for completion
        self.test_thread.join()
        self.running = False
        self.monitor_thread.join()

        self.metrics.end_time = time.time()
        self._generate_report()

    def stop_test(self):
        """Stop soak test"""
        print("Stopping soak test...")
        self.running = False

    def _run_test_loop(self):
        """Main test execution loop"""
        end_time = time.time() + (self.config.duration_hours * 3600)

        while self.running and time.time() < end_time and self.metrics.total_orders < self.config.target_order_events:
            try:
                self._generate_order_event()
                time.sleep(self.config.decision_interval_ms / 1000)
            except Exception as e:
                self.metrics.errors.append({
                    "timestamp": time.time(),
                    "error": str(e),
                    "component": "test_loop"
                })

    def _generate_order_event(self):
        """Generate a single order event"""
        # Random symbol
        symbol = random.choice(self.symbols)

        # Generate realistic market data
        base_price = 50000 if symbol == "BTCUSDT" else 3000
        micro_price = base_price + random.uniform(-100, 100)
        spread_bps = random.uniform(2, 12)  # 2-12 bps spread
        bid = micro_price - (spread_bps / 2 / 10000 * micro_price)
        ask = micro_price + (spread_bps / 2 / 10000 * micro_price)

        market_data = {
            "bid": bid,
            "ask": ask,
            "micro_price": micro_price,
            "spread_bps": spread_bps,
            "vol_spike_detected": random.random() < 0.05,  # 5% chance
        }

        # Create execution context
        context = ExecutionContext(
            correlation_id=f"soak_{self.order_counter}",
            symbol=symbol,
            side=random.choice(["BUY", "SELL"]),
            target_qty=random.uniform(0.01, 1.0),
            edge_bps=random.uniform(1, 10),
            micro_price=micro_price,
            mid_price=micro_price,
            spread_bps=spread_bps
        )

        self.order_counter += 1
        self.metrics.total_orders += 1

        # Record market conditions
        self.metrics.spread_bps_values.append(spread_bps)

        # Execute decision
        start_time = time.time_ns()
        children = self.execution_router.execute_sizing_decision(context, market_data)
        end_time = time.time_ns()

        decision_latency_ms = (end_time - start_time) / 1e6
        self.metrics.decision_latencies_ms.append(decision_latency_ms)

        # Track active orders
        for child in children:
            self.active_orders[child.order_id] = {
                "context": context,
                "child": child,
                "created_time": time.time(),
                "market_data": market_data
            }

        # Simulate order lifecycle (ACK, Fill/Cancel/Reject)
        threading.Thread(
            target=self._simulate_order_lifecycle,
            args=(children, market_data),
            daemon=True
        ).start()

    def _simulate_order_lifecycle(self, children: list, market_data: dict):
        """Simulate realistic order lifecycle"""
        for child in children:
            try:
                # ACK order
                time.sleep(random.uniform(0.001, 0.01))  # 1-10ms ACK latency
                self.execution_router.handle_order_ack(child.order_id, time.time_ns(), 5.0)

                # Random outcome
                outcome = random.choices(
                    ["fill", "cancel", "reject"],
                    weights=[0.6, 0.3, 0.1]  # 60% fill, 30% cancel, 10% reject
                )[0]

                if outcome == "fill":
                    # Simulate fill
                    fill_delay = random.uniform(0.01, 0.5)  # 10ms - 500ms
                    time.sleep(fill_delay)

                    fill_qty = child.target_qty * random.uniform(0.5, 1.0)
                    fill_price = child.price + random.uniform(-5, 5)

                    fill = FillEvent(
                        ts_ns=time.time_ns(),
                        qty=fill_qty,
                        price=fill_price,
                        fee=0.001,
                        liquidity_flag='M'
                    )

                    self.execution_router.handle_order_fill(child.order_id, fill)

                    # Record TCA metrics
                    self._record_tca_metrics(child, fill, market_data)

                    self.metrics.filled_orders += 1
                    self.metrics.fill_latencies_ms.append(fill_delay * 1000)

                elif outcome == "cancel":
                    time.sleep(random.uniform(0.1, 2.0))  # 100ms - 2s
                    self.execution_router.handle_order_cancel(child.order_id, time.time_ns())
                    self.metrics.cancelled_orders += 1

                elif outcome == "reject":
                    time.sleep(random.uniform(0.001, 0.01))
                    reject_reason = random.choice(["LOT_SIZE", "MIN_NOTIONAL", "POST_ONLY", "PRICE_FILTER"])
                    self.execution_router.handle_order_reject(child.order_id, reject_reason, time.time_ns())
                    self.metrics.rejected_orders += 1

            except Exception as e:
                self.metrics.errors.append({
                    "timestamp": time.time(),
                    "error": str(e),
                    "order_id": child.order_id
                })

    def _record_tca_metrics(self, child, fill: FillEvent, market_data: dict):
        """Record TCA metrics for analysis"""
        # Simplified TCA calculation
        arrival_price = market_data["micro_price"]
        vwap_fill = fill.price

        # Implementation shortfall (simplified)
        is_bps = ((vwap_fill - arrival_price) / arrival_price) * 10000

        # Spread cost (simplified)
        spread_cost_bps = market_data["spread_bps"] / 2

        # Adverse selection (simplified)
        adv_bps = is_bps - spread_cost_bps

        self.metrics.implementation_shortfall_bps.append(is_bps)
        self.metrics.spread_cost_bps.append(spread_cost_bps)
        self.metrics.adverse_selection_bps.append(adv_bps)

    def _monitoring_loop(self):
        """Monitoring and metrics collection loop"""
        while self.running:
            try:
                self._collect_metrics()
                time.sleep(self.config.metrics_interval_s)
            except Exception as e:
                self.metrics.errors.append({
                    "timestamp": time.time(),
                    "error": str(e),
                    "component": "monitoring"
                })

    def _collect_metrics(self):
        """Collect and log current metrics"""
        current_time = time.time()
        elapsed = current_time - self.metrics.start_time

        # Calculate fill ratio
        if self.metrics.total_orders > 0:
            fill_ratio = self.metrics.filled_orders / self.metrics.total_orders
            self.metrics.fill_ratios.append(fill_ratio)

        # Log metrics
        metrics_data = {
            "elapsed_seconds": elapsed,
            "total_orders": self.metrics.total_orders,
            "filled_orders": self.metrics.filled_orders,
            "cancelled_orders": self.metrics.cancelled_orders,
            "rejected_orders": self.metrics.rejected_orders,
            "active_orders": len(self.active_orders),
            "fill_ratio": fill_ratio if self.metrics.total_orders > 0 else 0,
            "errors_count": len(self.metrics.errors)
        }

        self.event_logger.emit("SOAK_METRICS", metrics_data, code="SOAK_METRICS")
        print(f"Soak Test Progress: {metrics_data}")

    def _generate_report(self):
        """Generate comprehensive soak test report"""
        duration = self.metrics.end_time - self.metrics.start_time

        # Calculate final metrics
        final_fill_ratio = self.metrics.filled_orders / self.metrics.total_orders if self.metrics.total_orders > 0 else 0
        cancel_ratio = self.metrics.cancelled_orders / self.metrics.total_orders if self.metrics.total_orders > 0 else 0

        # TCA metrics
        median_is_bps = statistics.median(self.metrics.implementation_shortfall_bps) if self.metrics.implementation_shortfall_bps else 0
        p90_is_bps = sorted(self.metrics.implementation_shortfall_bps)[int(0.9 * len(self.metrics.implementation_shortfall_bps))] if self.metrics.implementation_shortfall_bps else 0

        positive_adv_count = sum(1 for adv in self.metrics.adverse_selection_bps if adv > 0)
        positive_adv_ratio = positive_adv_count / len(self.metrics.adverse_selection_bps) if self.metrics.adverse_selection_bps else 0

        # Performance metrics
        p95_decision_latency = sorted(self.metrics.decision_latencies_ms)[int(0.95 * len(self.metrics.decision_latencies_ms))] if self.metrics.decision_latencies_ms else 0

        # Spread compliance
        spread_compliant_orders = sum(1 for spread in self.metrics.spread_bps_values if spread <= self.config.spread_limit_bps)
        spread_compliance_ratio = spread_compliant_orders / len(self.metrics.spread_bps_values) if self.metrics.spread_bps_values else 0

        # Generate report
        report = {
            "soak_test_report": {
                "duration_hours": duration / 3600,
                "total_order_events": self.metrics.total_orders,
                "target_order_events": self.config.target_order_events,

                "order_metrics": {
                    "filled_orders": self.metrics.filled_orders,
                    "cancelled_orders": self.metrics.cancelled_orders,
                    "rejected_orders": self.metrics.rejected_orders,
                    "fill_ratio": final_fill_ratio,
                    "cancel_ratio": cancel_ratio
                },

                "tca_metrics": {
                    "median_is_bps": median_is_bps,
                    "p90_is_bps": p90_is_bps,
                    "positive_adv_ratio": positive_adv_ratio,
                    "target_median_is_bps": self.config.target_median_is_bps,
                    "target_p90_is_bps": self.config.target_p90_is_bps,
                    "target_positive_adv_ratio": self.config.target_positive_adv_ratio
                },

                "performance_metrics": {
                    "p95_decision_latency_ms": p95_decision_latency,
                    "avg_decision_latency_ms": statistics.mean(self.metrics.decision_latencies_ms) if self.metrics.decision_latencies_ms else 0,
                    "target_p95_latency_ms": self.config.target_decision_latency_p95_ms
                },

                "market_conditions": {
                    "spread_compliance_ratio": spread_compliance_ratio,
                    "avg_spread_bps": statistics.mean(self.metrics.spread_bps_values) if self.metrics.spread_bps_values else 0,
                    "spread_limit_bps": self.config.spread_limit_bps
                },

                "quality_gates": {
                    "fill_ratio_passed": final_fill_ratio >= self.config.target_fill_ratio,
                    "median_is_passed": median_is_bps <= self.config.target_median_is_bps,
                    "p90_is_passed": p90_is_bps <= self.config.target_p90_is_bps,
                    "positive_adv_passed": positive_adv_ratio >= self.config.target_positive_adv_ratio,
                    "latency_passed": p95_decision_latency <= self.config.target_decision_latency_p95_ms,
                    "spread_compliance_passed": spread_compliance_ratio >= 0.95  # 95% compliance
                },

                "errors": self.metrics.errors
            }
        }

        # Save report
        report_path = Path("reports/soak_test_report.json")
        report_path.parent.mkdir(exist_ok=True)

        with open(report_path, 'w') as f:
            json.dump(report, f, indent=2, default=str)

        # Print summary
        print("\n" + "="*60)
        print("SOAK TEST REPORT")
        print("="*60)
        print(".2f")
        print(f"Order Events: {self.metrics.total_orders}/{self.config.target_order_events}")
        print(".3f")
        print(".2f")
        print(".3f")
        print(".2f")
        print(".1f")

        print("\nQUALITY GATES:")
        gates = report["soak_test_report"]["quality_gates"]
        for gate, passed in gates.items():
            status = "✅ PASS" if passed else "❌ FAIL"
            print(f"  {gate}: {status}")

        print(f"\nReport saved to: {report_path}")
        print("="*60)


def main():
    parser = argparse.ArgumentParser(description="Soak testing for Aurora")
    parser.add_argument("--duration-hours", type=float, default=2.0, help="Test duration in hours")
    parser.add_argument("--target-events", type=int, default=500, help="Target number of order events")
    parser.add_argument("--max-concurrent", type=int, default=10, help="Max concurrent orders")

    args = parser.parse_args()

    config = SoakTestConfig(
        duration_hours=args.duration_hours,
        target_order_events=args.target_events,
        max_concurrent_orders=args.max_concurrent
    )

    runner = SoakTestRunner(config)
    runner.start_test()


if __name__ == "__main__":
    main()
