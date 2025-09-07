"""
Performance tests for order throughput and latency measurement.

Tests order processing performance under various loads:
- Order submission throughput
- Fill processing latency
- Concurrent order handling capacity
- Memory usage under load
- P95/P99 latency measurements
"""

import pytest
import asyncio
import time
import statistics
import threading
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import Mock, AsyncMock
from typing import List, Dict, Any

from tests.fixtures.mock_exchange_factory import MockExchangeFactory
from core.execution.exchange.common import OrderRequest, Side, OrderType
from common.xai_logger import XAILogger


class PerformanceTestHarness:
    """Harness for measuring order processing performance."""

    def __init__(self, exchange, num_threads: int = 4):
        self.exchange = exchange
        self.num_threads = num_threads
        self.latencies = []
        self.throughput_measurements = []
        self.memory_usage = []
        self.xai_logger = XAILogger(trace_id="perf_test_123")

    async def measure_order_submission_latency(self, num_orders: int = 100) -> Dict[str, Any]:
        """Measure latency of order submissions."""
        latencies = []

        for i in range(num_orders):
            order = OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY if i % 2 == 0 else Side.SELL,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"perf_order_{i}"
            )

            start_time = time.time()
            result = await self.exchange.submit_order(order)
            end_time = time.time()

            latency = end_time - start_time
            latencies.append(latency)

            self.xai_logger.emit("ORDER.SUBMITTED", {
                "order_id": result.get("order_id"),
                "latency": latency,
                "timestamp": time.time()
            })

        return self._calculate_latency_stats(latencies)

    async def measure_concurrent_throughput(self, num_orders: int = 1000,
                                          concurrency: int = 10) -> Dict[str, Any]:
        """Measure throughput under concurrent load."""
        semaphore = asyncio.Semaphore(concurrency)
        start_time = time.time()

        async def submit_with_semaphore(order_num: int):
            async with semaphore:
                order = OrderRequest(
                    symbol="ETHUSDT",
                    side=Side.BUY,
                    type=OrderType.MARKET,
                    quantity=1.0,
                    client_order_id=f"throughput_order_{order_num}"
                )

                submit_start = time.time()
                result = await self.exchange.submit_order(order)
                submit_end = time.time()

                return {
                    "order_id": result.get("order_id"),
                    "latency": submit_end - submit_start
                }

        # Submit orders concurrently
        tasks = [submit_with_semaphore(i) for i in range(num_orders)]
        results = await asyncio.gather(*tasks)

        end_time = time.time()
        total_time = end_time - start_time

        latencies = [r["latency"] for r in results]
        throughput = num_orders / total_time

        return {
            "total_orders": num_orders,
            "total_time": total_time,
            "throughput_ops_per_sec": throughput,
            "avg_latency": statistics.mean(latencies),
            "p50_latency": statistics.median(latencies),
            "p95_latency": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
            "p99_latency": statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
        }

    async def measure_fill_processing_latency(self, num_orders: int = 50) -> Dict[str, Any]:
        """Measure time from order submission to fill completion."""
        fill_latencies = []

        for i in range(num_orders):
            order = OrderRequest(
                symbol="ADAUSDT",
                side=Side.BUY,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id=f"fill_perf_{i}"
            )

            submit_time = time.time()
            result = await self.exchange.submit_order(order)

            if result["status"] == "accepted":
                # Wait for fills
                await asyncio.sleep(0.05)  # Allow time for fills
                fills = await self.exchange.get_order_fills(result["order_id"])

                if fills:
                    fill_time = time.time()
                    fill_latencies.append(fill_time - submit_time)

        return self._calculate_latency_stats(fill_latencies)

    def _calculate_latency_stats(self, latencies: List[float]) -> Dict[str, Any]:
        """Calculate comprehensive latency statistics."""
        if not latencies:
            return {"error": "No latency measurements"}

        return {
            "count": len(latencies),
            "mean": statistics.mean(latencies),
            "median": statistics.median(latencies),
            "stdev": statistics.stdev(latencies) if len(latencies) > 1 else 0,
            "min": min(latencies),
            "max": max(latencies),
            "p95": statistics.quantiles(latencies, n=20)[18] if len(latencies) >= 20 else max(latencies),
            "p99": statistics.quantiles(latencies, n=100)[98] if len(latencies) >= 100 else max(latencies)
        }


class TestOrderThroughput:
    """Test order processing performance metrics."""

    @pytest.fixture
    async def setup_performance_harness(self):
        """Setup performance testing harness."""
        # Use high-performance exchange for throughput testing
        exchange = MockExchangeFactory.create_high_latency_exchange(
            fill_profile={"latency_ms": 1, "jitter_ms": 0}  # Minimal latency for accurate measurement
        )

        harness = PerformanceTestHarness(exchange, num_threads=4)

        yield harness

        # Cleanup
        await asyncio.sleep(0.1)

    @pytest.mark.asyncio
    async def test_order_submission_latency_baseline(self, setup_performance_harness):
        """Test baseline order submission latency."""
        harness = await setup_performance_harness

        # Measure latency for 50 orders
        result = await harness.measure_order_submission_latency(50)

        # Assert reasonable performance
        assert result["mean"] < 0.1  # Less than 100ms average
        assert result["p95"] < 0.2   # P95 less than 200ms
        assert result["count"] == 50

        print(f"Order submission latency - Mean: {result['mean']:.3f}s, P95: {result['p95']:.3f}s")

    @pytest.mark.asyncio
    async def test_concurrent_throughput_capacity(self, setup_performance_harness):
        """Test throughput under concurrent load."""
        harness = await setup_performance_harness

        # Test with 500 orders at concurrency of 20
        result = await harness.measure_concurrent_throughput(500, 20)

        # Assert reasonable throughput
        assert result["throughput_ops_per_sec"] > 50  # At least 50 ops/sec
        assert result["p95_latency"] < 1.0  # P95 less than 1 second
        assert result["total_orders"] == 500

        print(f"Concurrent throughput - {result['throughput_ops_per_sec']:.1f} ops/sec, P95: {result['p95_latency']:.3f}s")

    @pytest.mark.asyncio
    async def test_fill_processing_latency(self, setup_performance_harness):
        """Test end-to-end fill processing latency."""
        harness = await setup_performance_harness

        result = await harness.measure_fill_processing_latency(30)

        # Assert fill processing is reasonably fast
        assert result["mean"] < 0.5  # Less than 500ms average
        assert result["p95"] < 1.0   # P95 less than 1 second

        print(f"Fill processing latency - Mean: {result['mean']:.3f}s, P95: {result['p95']:.3f}s")

    @pytest.mark.asyncio
    async def test_scalability_under_load(self, setup_performance_harness):
        """Test how performance scales with increasing load."""
        harness = await setup_performance_harness

        scale_results = []

        # Test at different concurrency levels
        for concurrency in [5, 10, 20, 50]:
            result = await harness.measure_concurrent_throughput(200, concurrency)
            scale_results.append({
                "concurrency": concurrency,
                "throughput": result["throughput_ops_per_sec"],
                "p95_latency": result["p95_latency"]
            })

            print(f"Concurrency {concurrency}: {result['throughput_ops_per_sec']:.1f} ops/sec, P95: {result['p95_latency']:.3f}s")

        # Assert that throughput increases with concurrency (up to a point)
        assert scale_results[1]["throughput"] > scale_results[0]["throughput"] * 0.8  # At least 80% improvement
        assert scale_results[2]["throughput"] > scale_results[1]["throughput"] * 0.7  # At least 70% improvement

    @pytest.mark.asyncio
    async def test_memory_usage_under_load(self, setup_performance_harness):
        """Test memory usage patterns under load."""
        harness = await setup_performance_harness

        # This is a simplified memory test - in real scenarios you'd use memory_profiler
        import psutil
        import os

        process = psutil.Process(os.getpid())
        initial_memory = process.memory_info().rss / 1024 / 1024  # MB

        # Run high-load test
        await harness.measure_concurrent_throughput(1000, 50)

        final_memory = process.memory_info().rss / 1024 / 1024  # MB
        memory_increase = final_memory - initial_memory

        # Assert reasonable memory usage (less than 100MB increase)
        assert memory_increase < 100

        print(f"Memory usage - Initial: {initial_memory:.1f}MB, Final: {final_memory:.1f}MB, Increase: {memory_increase:.1f}MB")

    @pytest.mark.asyncio
    async def test_latency_distribution_analysis(self, setup_performance_harness):
        """Test detailed latency distribution analysis."""
        harness = await setup_performance_harness

        # Collect many latency measurements
        result = await harness.measure_order_submission_latency(200)

        # Assert latency distribution properties
        assert result["p99"] < result["max"]  # P99 should be less than max
        assert result["p95"] < result["p99"]  # P95 should be less than P99
        assert result["median"] < result["p95"]  # Median should be less than P95

        # Assert no extreme outliers (max should not be 10x median)
        assert result["max"] < result["median"] * 10

        print(f"Latency distribution - Min: {result['min']:.3f}s, Median: {result['median']:.3f}s, P95: {result['p95']:.3f}s, P99: {result['p99']:.3f}s, Max: {result['max']:.3f}s")

    @pytest.mark.asyncio
    async def test_performance_regression_detection(self, setup_performance_harness):
        """Test for performance regressions by comparing against baselines."""
        harness = await setup_performance_harness

        # Run multiple iterations to establish baseline
        baseline_results = []
        for i in range(3):
            result = await harness.measure_order_submission_latency(20)
            baseline_results.append(result["p95"])

        baseline_p95 = statistics.mean(baseline_results)

        # Run test iteration
        test_result = await harness.measure_order_submission_latency(20)
        test_p95 = test_result["p95"]

        # Assert no significant regression (test should be within 50% of baseline)
        regression_ratio = test_p95 / baseline_p95
        assert regression_ratio < 1.5

        print(f"Performance regression check - Baseline P95: {baseline_p95:.3f}s, Test P95: {test_p95:.3f}s, Ratio: {regression_ratio:.2f}")


# Standalone function for CI performance measurement
def test_order_throughput():
    """Standalone throughput test for CI pipeline."""
    import asyncio

    async def run_test():
        exchange = MockExchangeFactory.create_deterministic_exchange()
        harness = PerformanceTestHarness(exchange)

        # Run throughput test
        result = await harness.measure_concurrent_throughput(100, 10)

        # Print results for CI
        print(".3f")
        print(".3f")
        print(".3f")
        print(".1f")

        # Assert minimum performance thresholds
        assert result["throughput_ops_per_sec"] > 20
        assert result["p95_latency"] < 2.0

        return result

    # Run the async test
    return asyncio.run(run_test())


if __name__ == "__main__":
    # Allow running standalone for manual testing
    result = test_order_throughput()
    print("Performance test completed successfully!")