"""
Tests for enhanced exchange circuit breaker implementation.
Tests the recovery timeout logic, adaptive timeout, health checks, and state management.
"""

import time
import pytest
from unittest.mock import Mock, patch
from core.execution.exchange.error_handling import (
    ExchangeCircuitBreaker,
    CircuitBreakerConfig,
    CircuitBreakerState,
    ExchangeError
)


class TestExchangeCircuitBreaker:
    """Test enhanced circuit breaker functionality."""
    
    def test_initial_state_closed(self):
        """Test circuit breaker starts in CLOSED state."""
        config = CircuitBreakerConfig()
        breaker = ExchangeCircuitBreaker(config)
        
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.get_stats()["failure_count"] == 0
        assert breaker.get_stats()["consecutive_failures"] == 0
    
    def test_successful_operation_stays_closed(self):
        """Test successful operations keep circuit breaker CLOSED."""
        config = CircuitBreakerConfig()
        breaker = ExchangeCircuitBreaker(config)
        
        # Successful operation
        result = breaker.call(lambda: "success")
        
        assert result == "success"
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.get_stats()["consecutive_failures"] == 0
    
    def test_failure_threshold_opens_circuit(self):
        """Test circuit opens after failure threshold."""
        config = CircuitBreakerConfig(failure_threshold=3)
        breaker = ExchangeCircuitBreaker(config)
        
        # Trigger failures up to threshold
        for i in range(3):
            with pytest.raises(Exception):
                breaker.call(lambda: exec('raise Exception("test error")'))
        
        assert breaker.state == CircuitBreakerState.OPEN
        assert breaker.get_stats()["failure_count"] == 3
        assert breaker.get_stats()["consecutive_failures"] == 3
    
    def test_open_circuit_blocks_operations(self):
        """Test open circuit blocks operations until recovery timeout."""
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1.0)
        breaker = ExchangeCircuitBreaker(config)
        
        # Trigger failures to open circuit
        for i in range(2):
            with pytest.raises(Exception):
                breaker.call(lambda: exec('raise Exception("test error")'))
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Operations should be blocked
        with pytest.raises(ExchangeError, match="Circuit breaker is OPEN"):
            breaker.call(lambda: "success")
    
    @patch('time.time')
    def test_recovery_timeout_allows_half_open(self, mock_time):
        """Test circuit transitions to HALF_OPEN after recovery timeout."""
        config = CircuitBreakerConfig(failure_threshold=2, recovery_timeout=1.0)
        breaker = ExchangeCircuitBreaker(config)
        
        # Set initial time
        mock_time.return_value = 1000.0
        
        # Trigger failures to open circuit
        for i in range(2):
            with pytest.raises(Exception):
                breaker.call(lambda: exec('raise Exception("test error")'))
        
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Time passes beyond recovery timeout
        mock_time.return_value = 1002.0  # 2 seconds later
        
        # Next operation should transition to HALF_OPEN
        result = breaker.call(lambda: "recovery_success")
        
        assert result == "recovery_success"
        assert breaker.state == CircuitBreakerState.HALF_OPEN
    
    @patch('time.time')
    def test_half_open_success_threshold_closes_circuit(self, mock_time):
        """Test HALF_OPEN transitions to CLOSED after success threshold."""
        config = CircuitBreakerConfig(
            failure_threshold=2, 
            recovery_timeout=1.0,
            success_threshold=3
        )
        breaker = ExchangeCircuitBreaker(config)
        
        # Set initial time
        mock_time.return_value = 1000.0
        
        # Trigger failures to open circuit
        for i in range(2):
            with pytest.raises(Exception):
                breaker.call(lambda: exec('raise Exception("test error")'))
        
        # Time passes beyond recovery timeout
        mock_time.return_value = 1002.0
        
        # Transition to HALF_OPEN
        breaker.call(lambda: "success1")
        assert breaker.state == CircuitBreakerState.HALF_OPEN
        
        # Continue with successful operations
        breaker.call(lambda: "success2")
        assert breaker.state == CircuitBreakerState.HALF_OPEN
        
        # Final success should close circuit
        breaker.call(lambda: "success3")
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.get_stats()["consecutive_failures"] == 0
    
    @patch('time.time')
    def test_half_open_failure_reopens_circuit(self, mock_time):
        """Test HALF_OPEN failure reopens circuit with adaptive timeout."""
        config = CircuitBreakerConfig(
            failure_threshold=2, 
            recovery_timeout=1.0,
            adaptive_timeout=True
        )
        breaker = ExchangeCircuitBreaker(config)
        
        # Set initial time
        mock_time.return_value = 1000.0
        
        # Trigger failures to open circuit
        for i in range(2):
            with pytest.raises(Exception):
                breaker.call(lambda: exec('raise Exception("test error")'))
        
        # Time passes beyond recovery timeout
        mock_time.return_value = 1002.0
        
        # Transition to HALF_OPEN
        breaker.call(lambda: "success")
        assert breaker.state == CircuitBreakerState.HALF_OPEN
        
        # Failure in HALF_OPEN should reopen with adaptive timeout
        with pytest.raises(Exception):
            breaker.call(lambda: exec('raise Exception("half_open_failure")'))
        
        assert breaker.state == CircuitBreakerState.OPEN
        stats = breaker.get_stats()
        # Multiplier increases from 1.0 -> 1.5 (first OPEN) -> 2.25 (second OPEN from HALF_OPEN)
        assert stats["adaptive_timeout_multiplier"] > 1.5
    
    def test_adaptive_timeout_multiplier_increases(self):
        """Test adaptive timeout multiplier increases with repeated failures."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=1.0,
            adaptive_timeout=True,
            max_recovery_timeout=10.0
        )
        breaker = ExchangeCircuitBreaker(config)
        
        # Initial adaptive multiplier should be 1.0
        assert breaker.get_stats()["adaptive_timeout_multiplier"] == 1.0
        
        # Force circuit open with failures
        for i in range(2):
            with pytest.raises(Exception):
                breaker.call(lambda: exec('raise Exception("test error")'))
        
        # Multiplier should increase after transition to OPEN from HALF_OPEN
        breaker._state = CircuitBreakerState.HALF_OPEN
        with pytest.raises(Exception):
            breaker.call(lambda: exec('raise Exception("half_open_failure")'))
        
        # Multiplier increases: 1.0 -> 1.5 (first OPEN) -> 2.25 (second OPEN from HALF_OPEN)
        assert breaker.get_stats()["adaptive_timeout_multiplier"] > 1.5
    
    def test_gradual_recovery_limits_half_open_requests(self):
        """Test gradual recovery limits requests in HALF_OPEN state."""
        config = CircuitBreakerConfig(
            failure_threshold=2,
            recovery_timeout=0.1,
            gradual_recovery=True
        )
        breaker = ExchangeCircuitBreaker(config)
        
        # Force to HALF_OPEN state
        breaker._state = CircuitBreakerState.HALF_OPEN
        breaker._half_open_request_count = 3  # At limit
        
        # Should block additional requests
        with pytest.raises(ExchangeError, match="gradual recovery limit reached"):
            breaker.call(lambda: "success")
    
    def test_health_check_enabled(self):
        """Test health check functionality when enabled."""
        config = CircuitBreakerConfig(
            health_check_enabled=True,
            health_check_interval=0.1
        )
        breaker = ExchangeCircuitBreaker(config)
        
        # Health check should not raise exceptions
        breaker._perform_health_check()
        
        # Should update last health check time
        assert breaker._last_health_check > 0
    
    def test_force_open_and_close(self):
        """Test manual force open/close functionality."""
        config = CircuitBreakerConfig()
        breaker = ExchangeCircuitBreaker(config)
        
        # Force open
        breaker.force_open()
        assert breaker.state == CircuitBreakerState.OPEN
        
        # Force close
        breaker.force_close()
        assert breaker.state == CircuitBreakerState.CLOSED
        assert breaker.get_stats()["failure_count"] == 0
        assert breaker.get_stats()["consecutive_failures"] == 0
        assert breaker.get_stats()["adaptive_timeout_multiplier"] == 1.0
    
    def test_get_stats_comprehensive(self):
        """Test comprehensive statistics reporting."""
        config = CircuitBreakerConfig()
        breaker = ExchangeCircuitBreaker(config)
        
        stats = breaker.get_stats()
        
        # Check all expected keys are present
        expected_keys = {
            "state", "failure_count", "consecutive_failures", "success_count",
            "total_operations", "adaptive_timeout_multiplier", 
            "remaining_recovery_time", "failure_rate"
        }
        assert set(stats.keys()) >= expected_keys
        
        # Check initial values
        assert stats["state"] == CircuitBreakerState.CLOSED.value
        assert stats["failure_rate"] == 0.0
        assert stats["total_operations"] == 0
    
    @patch('time.time')
    def test_remaining_recovery_time_calculation(self, mock_time):
        """Test accurate recovery time calculation."""
        config = CircuitBreakerConfig(
            failure_threshold=1,
            recovery_timeout=5.0,
            adaptive_timeout=False  # Disable adaptive timeout for this test
        )
        breaker = ExchangeCircuitBreaker(config)
        
        # Set time and trigger failure
        mock_time.return_value = 1000.0
        with pytest.raises(Exception):
            breaker.call(lambda: exec('raise Exception("test error")'))
        
        # Check remaining time
        mock_time.return_value = 1002.0  # 2 seconds later
        remaining = breaker._get_remaining_recovery_time()
        assert remaining == 3.0  # 5.0 - 2.0
    
    def test_mock_time_handling(self):
        """Test graceful handling of mock time objects in tests."""
        config = CircuitBreakerConfig()
        breaker = ExchangeCircuitBreaker(config)
        
        # Mock time that causes TypeError should be handled gracefully
        with patch('time.time', side_effect=TypeError("Mock time error")):
            # Should not raise exception
            result = breaker._should_attempt_reset()
            assert result is False
            
            # Health check should also handle gracefully
            breaker._perform_health_check()