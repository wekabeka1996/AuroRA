"""
Unit Tests — Enhanced Circuit Breaker Recovery
============================================

Test enhanced circuit breaker with automatic recovery mechanisms,
adaptive timeouts, health checks, and gradual recovery features.
"""

from __future__ import annotations

import pytest
import time
from unittest.mock import Mock, patch
from dataclasses import dataclass

from core.execution.exchange.error_handling import (
    ExchangeCircuitBreaker, 
    CircuitBreakerConfig, 
    CircuitBreakerState,
    ExchangeError
)


class TestEnhancedCircuitBreaker:
    """Test enhanced circuit breaker recovery features"""

    @pytest.fixture
    def basic_config(self):
        """Basic circuit breaker config for testing"""
        return CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,
            success_threshold=2,
            adaptive_timeout=True,
            health_check_enabled=True,
            health_check_interval=0.05,
            gradual_recovery=True
        )

    @pytest.fixture
    def circuit_breaker(self, basic_config):
        """Create test circuit breaker"""
        return ExchangeCircuitBreaker(basic_config)

    def test_adaptive_timeout_increases_on_failures(self, circuit_breaker):
        """Test adaptive timeout increases after repeated failures"""
        # Initial failures to open circuit
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Wait for initial recovery timeout
        time.sleep(0.2)
        
        # Try recovery but fail again (should increase adaptive timeout)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        stats = circuit_breaker.get_stats()
        assert stats["adaptive_timeout_multiplier"] > 1.0
        assert stats["state"] == "open"

    def test_gradual_recovery_limits_requests(self, circuit_breaker):
        """Test gradual recovery limits requests in HALF_OPEN state"""
        # Open the circuit
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Wait for recovery
        time.sleep(0.2)
        
        # First request should put it in HALF_OPEN
        result1 = circuit_breaker.call(lambda: "success1")
        assert result1 == "success1"
        assert circuit_breaker.state == CircuitBreakerState.HALF_OPEN
        
        # Should allow limited requests
        result2 = circuit_breaker.call(lambda: "success2")
        assert result2 == "success2"
        
        # Should close after enough successes
        result3 = circuit_breaker.call(lambda: "success3")
        assert result3 == "success3"
        assert circuit_breaker.state == CircuitBreakerState.CLOSED

    def test_health_check_logging(self, circuit_breaker):
        """Test health check provides useful logging"""
        # Open the circuit
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        # Circuit should be open now
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Wait enough time to trigger health check interval
        time.sleep(0.1)
        
        # Try calling - should trigger health check and reject
        with pytest.raises(ExchangeError) as exc_info:
            circuit_breaker.call(lambda: "test")
        
        # Error should indicate circuit is open
        assert "Circuit breaker is OPEN" in str(exc_info.value)

    def test_circuit_breaker_statistics(self, circuit_breaker):
        """Test circuit breaker provides comprehensive statistics"""
        # Perform some operations
        circuit_breaker.call(lambda: "success")  # Success
        
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)  # Failure
            
        stats = circuit_breaker.get_stats()
        
        assert "state" in stats
        assert "failure_count" in stats
        assert "consecutive_failures" in stats
        assert "success_count" in stats
        assert "total_operations" in stats
        assert "adaptive_timeout_multiplier" in stats
        assert "remaining_recovery_time" in stats
        assert "failure_rate" in stats
        
        assert stats["total_operations"] == 2
        assert stats["failure_count"] == 1
        assert stats["failure_rate"] == 0.5

    def test_force_open_and_close(self, circuit_breaker):
        """Test manual force open/close operations"""
        # Initially closed
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        
        # Force open
        circuit_breaker.force_open()
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Should reject requests
        with pytest.raises(ExchangeError):
            circuit_breaker.call(lambda: "test")
        
        # Force close
        circuit_breaker.force_close()
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        
        # Should work normally
        result = circuit_breaker.call(lambda: "success")
        assert result == "success"

    def test_enhanced_error_messages(self, circuit_breaker):
        """Test enhanced error messages with recovery time"""
        # Open the circuit
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        # Error message should include recovery time
        with pytest.raises(ExchangeError) as exc_info:
            circuit_breaker.call(lambda: "test")
        
        error_msg = str(exc_info.value)
        assert "recovery in" in error_msg
        assert "s" in error_msg  # seconds

    def test_reset_adaptive_timeout_on_success(self, circuit_breaker):
        """Test adaptive timeout resets after successful recovery"""
        # Open circuit and increase timeout
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        time.sleep(0.2)
        
        # Fail recovery to increase timeout
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        stats1 = circuit_breaker.get_stats()
        assert stats1["adaptive_timeout_multiplier"] > 1.0
        
        # Wait and successfully recover
        time.sleep(0.5)
        circuit_breaker.call(lambda: "success")
        circuit_breaker.call(lambda: "success")
        
        # Should be closed and timeout reset
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        stats2 = circuit_breaker.get_stats()
        assert stats2["adaptive_timeout_multiplier"] == 1.0

    def test_consecutive_failures_tracking(self, circuit_breaker):
        """Test consecutive failures tracking vs total failures"""
        # Success, then failures
        circuit_breaker.call(lambda: "success")
        
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        with pytest.raises(ZeroDivisionError):
            circuit_breaker.call(lambda: 1 / 0)
        
        stats = circuit_breaker.get_stats()
        assert stats["total_operations"] == 3
        assert stats["failure_count"] == 2
        assert stats["consecutive_failures"] == 2
        
        # Circuit should be OPEN now
        assert circuit_breaker.state == CircuitBreakerState.OPEN
        
        # Wait for recovery timeout
        time.sleep(0.2)
        
        # Successful calls should recover and close circuit
        circuit_breaker.call(lambda: "success1")  # HALF_OPEN
        circuit_breaker.call(lambda: "success2")  # Should close circuit
        
        # Check state and stats
        assert circuit_breaker.state == CircuitBreakerState.CLOSED
        stats2 = circuit_breaker.get_stats()
        assert stats2["consecutive_failures"] == 0
        assert stats2["failure_count"] == 0  # Should reset on full recovery

    def test_max_recovery_timeout_cap(self):
        """Test adaptive timeout respects maximum cap"""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=0.1,
            adaptive_timeout=True,
            max_recovery_timeout=0.5
        )
        
        breaker = ExchangeCircuitBreaker(config)
        
        # Force many failures to increase timeout
        for _ in range(10):
            try:
                with pytest.raises(ZeroDivisionError):
                    breaker.call(lambda: 1 / 0)
                time.sleep(0.2)
                with pytest.raises(ZeroDivisionError):
                    breaker.call(lambda: 1 / 0)
            except ExchangeError:
                pass  # Circuit already open
        
        stats = breaker.get_stats()
        remaining_time = stats["remaining_recovery_time"]
        assert remaining_time <= 0.5  # Should respect max timeout


if __name__ == "__main__":
    pytest.main([__file__, "-v"])