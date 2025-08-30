from __future__ import annotations

"""
Exchange Error Handling and Logging
===================================

Comprehensive error handling and logging for exchange operations:
- Structured error types with context
- Retry mechanisms with exponential backoff
- Comprehensive logging with correlation IDs
- Circuit breaker pattern for fault tolerance
- Metrics collection for monitoring
"""

import logging
import time
import threading
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional, Any, Callable
from contextlib import contextmanager

from core.execution.exchange.common import ExchangeError, ValidationError, RateLimitError

logger = logging.getLogger(__name__)


class ErrorSeverity(Enum):
    """Error severity levels."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ErrorCategory(Enum):
    """Error categories for classification."""
    NETWORK = "network"
    AUTHENTICATION = "authentication"
    VALIDATION = "validation"
    RATE_LIMIT = "rate_limit"
    EXCHANGE_SPECIFIC = "exchange_specific"
    SYSTEM = "system"


@dataclass
class ExchangeErrorContext:
    """Context information for exchange errors."""
    exchange_name: str
    operation: str
    symbol: Optional[str] = None
    order_id: Optional[str] = None
    client_order_id: Optional[str] = None
    request_params: Optional[Dict[str, Any]] = None
    response_data: Optional[Dict[str, Any]] = None
    timestamp_ns: int = 0
    correlation_id: Optional[str] = None

    def __post_init__(self):
        if self.timestamp_ns == 0:
            self.timestamp_ns = time.time_ns()


@dataclass
class ExchangeErrorInfo:
    """Structured error information."""
    error: Exception
    category: ErrorCategory
    severity: ErrorSeverity
    context: ExchangeErrorContext
    retryable: bool = False
    retry_after_seconds: Optional[float] = None
    user_message: Optional[str] = None

    @property
    def error_code(self) -> str:
        """Get standardized error code."""
        return f"{self.category.value}_{self.error.__class__.__name__}"

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging/serialization."""
        return {
            "error_code": self.error_code,
            "error_message": str(self.error),
            "category": self.category.value,
            "severity": self.severity.value,
            "retryable": self.retryable,
            "retry_after_seconds": self.retry_after_seconds,
            "user_message": self.user_message,
            "context": {
                "exchange_name": self.context.exchange_name,
                "operation": self.context.operation,
                "symbol": self.context.symbol,
                "order_id": self.context.order_id,
                "client_order_id": self.context.client_order_id,
                "correlation_id": self.context.correlation_id,
                "timestamp_ns": self.context.timestamp_ns,
            }
        }


class ExchangeErrorHandler:
    """Handles exchange errors with classification and recovery strategies."""

    def __init__(self):
        self._error_patterns = self._build_error_patterns()

    def _build_error_patterns(self) -> Dict[str, Dict[str, Any]]:
        """Build error pattern matching rules."""
        return {
            # Network errors
            "ConnectionError": {
                "category": ErrorCategory.NETWORK,
                "severity": ErrorSeverity.HIGH,
                "retryable": True,
                "retry_after_seconds": 1.0,
            },
            "TimeoutError": {
                "category": ErrorCategory.NETWORK,
                "severity": ErrorSeverity.MEDIUM,
                "retryable": True,
                "retry_after_seconds": 0.5,
            },
            "HTTPError": {
                "category": ErrorCategory.NETWORK,
                "severity": ErrorSeverity.MEDIUM,
                "retryable": True,
                "retry_after_seconds": 2.0,
            },
            # Authentication errors
            "AuthenticationError": {
                "category": ErrorCategory.AUTHENTICATION,
                "severity": ErrorSeverity.CRITICAL,
                "retryable": False,
            },
            "InvalidCredentials": {
                "category": ErrorCategory.AUTHENTICATION,
                "severity": ErrorSeverity.CRITICAL,
                "retryable": False,
            },
            # Rate limit errors
            "RateLimitError": {
                "category": ErrorCategory.RATE_LIMIT,
                "severity": ErrorSeverity.MEDIUM,
                "retryable": True,
                "retry_after_seconds": 5.0,
            },
            "TooManyRequests": {
                "category": ErrorCategory.RATE_LIMIT,
                "severity": ErrorSeverity.MEDIUM,
                "retryable": True,
                "retry_after_seconds": 10.0,
            },
            # Validation errors
            "ValidationError": {
                "category": ErrorCategory.VALIDATION,
                "severity": ErrorSeverity.LOW,
                "retryable": False,
            },
            "InvalidOrder": {
                "category": ErrorCategory.VALIDATION,
                "severity": ErrorSeverity.LOW,
                "retryable": False,
            },
        }

    def classify_error(self, error: Exception, context: ExchangeErrorContext) -> ExchangeErrorInfo:
        """Classify an error and create structured error info."""
        error_type = error.__class__.__name__

        # Check for known error patterns
        pattern = self._error_patterns.get(error_type, {})

        # Default classification
        category = pattern.get("category", ErrorCategory.EXCHANGE_SPECIFIC)
        severity = pattern.get("severity", ErrorSeverity.MEDIUM)
        retryable = pattern.get("retryable", False)
        retry_after = pattern.get("retry_after_seconds")

        # Special handling for HTTP status codes
        error_dict = vars(error)
        if 'response' in error_dict and hasattr(error_dict['response'], 'status_code'):
            status_code = error_dict['response'].status_code
            if status_code == 429:
                category = ErrorCategory.RATE_LIMIT
                severity = ErrorSeverity.MEDIUM
                retryable = True
                retry_after = 30.0
            elif status_code >= 500:
                category = ErrorCategory.NETWORK
                severity = ErrorSeverity.HIGH
                retryable = True
                retry_after = 5.0
            elif status_code == 401 or status_code == 403:
                category = ErrorCategory.AUTHENTICATION
                severity = ErrorSeverity.CRITICAL
                retryable = False

        # Generate user-friendly message
        user_message = self._generate_user_message(error, category, context)

        return ExchangeErrorInfo(
            error=error,
            category=category,
            severity=severity,
            context=context,
            retryable=retryable,
            retry_after_seconds=retry_after,
            user_message=user_message
        )

    def _generate_user_message(self, error: Exception, category: ErrorCategory,
                              context: ExchangeErrorContext) -> str:
        """Generate user-friendly error message."""
        base_messages = {
            ErrorCategory.NETWORK: f"Network connectivity issue with {context.exchange_name}",
            ErrorCategory.AUTHENTICATION: f"Authentication failed with {context.exchange_name}",
            ErrorCategory.VALIDATION: f"Invalid request to {context.exchange_name}",
            ErrorCategory.RATE_LIMIT: f"Rate limit exceeded on {context.exchange_name}",
            ErrorCategory.EXCHANGE_SPECIFIC: f"Exchange error on {context.exchange_name}",
            ErrorCategory.SYSTEM: f"System error with {context.exchange_name}",
        }

        message = base_messages.get(category, f"Error with {context.exchange_name}")
        if context.symbol:
            message += f" for {context.symbol}"
        if context.operation:
            message += f" during {context.operation}"

        return message


class RetryConfig:
    """Configuration for retry behavior."""

    def __init__(self,
                 max_attempts: int = 3,
                 base_delay: float = 1.0,
                 max_delay: float = 60.0,
                 backoff_factor: float = 2.0,
                 jitter: bool = True):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.backoff_factor = backoff_factor
        self.jitter = jitter


class ExchangeRetryHandler:
    """Handles retry logic with exponential backoff."""

    def __init__(self, config: RetryConfig):
        self.config = config

    def execute_with_retry(self, operation: Callable[[], Any],
                          error_handler: ExchangeErrorHandler,
                          context: ExchangeErrorContext) -> Any:
        """Execute operation with retry logic."""
        last_error = None

        for attempt in range(self.config.max_attempts):
            try:
                return operation()
            except Exception as e:
                last_error = e
                error_info = error_handler.classify_error(e, context)

                # Log the error
                logger.warning(
                    f"Exchange operation failed (attempt {attempt + 1}/{self.config.max_attempts}): "
                    f"{error_info.error_code} - {e}"
                )

                # Check if we should retry
                if not error_info.retryable or attempt == self.config.max_attempts - 1:
                    break

                # Calculate delay
                delay = self._calculate_delay(attempt, error_info.retry_after_seconds)

                # Log retry
                logger.info(
                    f"Retrying {context.operation} in {delay:.2f}s "
                    f"(attempt {attempt + 2}/{self.config.max_attempts})"
                )

                time.sleep(delay)

        # All retries exhausted
        if last_error:
            error_info = error_handler.classify_error(last_error, context)
            logger.error(
                f"Exchange operation failed after {self.config.max_attempts} attempts: "
                f"{error_info.error_code} - {last_error}"
            )
            raise last_error

    def _calculate_delay(self, attempt: int, suggested_delay: Optional[float]) -> float:
        """Calculate delay for next retry attempt."""
        if suggested_delay is not None:
            delay = suggested_delay
        else:
            delay = self.config.base_delay * (self.config.backoff_factor ** attempt)

        # Apply maximum delay
        delay = min(delay, self.config.max_delay)

        # Add jitter if enabled
        if self.config.jitter:
            import random
            delay *= (0.5 + random.random() * 0.5)  # 50-100% of calculated delay

        return delay


class CircuitBreakerState(Enum):
    """Circuit breaker states."""
    CLOSED = "closed"      # Normal operation
    OPEN = "open"          # Failing, requests rejected
    HALF_OPEN = "half_open"  # Testing if service recovered


@dataclass
class CircuitBreakerConfig:
    """Configuration for circuit breaker."""
    failure_threshold: int = 5      # Failures before opening
    recovery_timeout: float = 60.0  # Seconds before attempting recovery
    success_threshold: int = 3      # Successes needed to close circuit


class ExchangeCircuitBreaker:
    """Circuit breaker for exchange operations."""

    def __init__(self, config: CircuitBreakerConfig):
        self.config = config
        self._state = CircuitBreakerState.CLOSED
        self._failure_count = 0
        self._success_count = 0
        self._last_failure_time = 0.0
        self._lock = threading.Lock()

    def call(self, operation: Callable[[], Any]) -> Any:
        """Execute operation through circuit breaker."""
        with self._lock:
            if self._state == CircuitBreakerState.OPEN:
                if self._should_attempt_reset():
                    self._state = CircuitBreakerState.HALF_OPEN
                    self._success_count = 0
                else:
                    raise ExchangeError("Circuit breaker is OPEN")

            try:
                result = operation()
                self._on_success()
                return result
            except Exception as e:
                self._on_failure()
                raise e

    def _should_attempt_reset(self) -> bool:
        """Check if we should attempt to reset the circuit."""
        return (time.time() - self._last_failure_time) >= self.config.recovery_timeout

    def _on_success(self):
        """Handle successful operation."""
        if self._state == CircuitBreakerState.HALF_OPEN:
            self._success_count += 1
            if self._success_count >= self.config.success_threshold:
                self._state = CircuitBreakerState.CLOSED
                self._failure_count = 0
                logger.info("Circuit breaker CLOSED - service recovered")

    def _on_failure(self):
        """Handle failed operation."""
        self._failure_count += 1
        self._last_failure_time = time.time()

        if self._state == CircuitBreakerState.HALF_OPEN:
            self._state = CircuitBreakerState.OPEN
            logger.warning("Circuit breaker OPEN - service still failing")
        elif (self._state == CircuitBreakerState.CLOSED and
              self._failure_count >= self.config.failure_threshold):
            self._state = CircuitBreakerState.OPEN
            logger.warning("Circuit breaker OPEN - failure threshold exceeded")

    @property
    def state(self) -> CircuitBreakerState:
        """Get current circuit breaker state."""
        return self._state


@contextmanager
def exchange_operation_context(exchange_name: str, operation: str,
                              symbol: Optional[str] = None,
                              order_id: Optional[str] = None,
                              client_order_id: Optional[str] = None,
                              correlation_id: Optional[str] = None):
    """Context manager for exchange operations with automatic error handling."""
    context = ExchangeErrorContext(
        exchange_name=exchange_name,
        operation=operation,
        symbol=symbol,
        order_id=order_id,
        client_order_id=client_order_id,
        correlation_id=correlation_id
    )

    start_time = time.time_ns()
    try:
        logger.info(f"Starting {operation} on {exchange_name}" +
                   (f" for {symbol}" if symbol else ""))
        yield context
    except Exception as e:
        duration_ms = (time.time_ns() - start_time) / 1_000_000
        error_handler = ExchangeErrorHandler()
        error_info = error_handler.classify_error(e, context)

        # Log structured error
        logger.error(
            f"Exchange operation failed after {duration_ms:.2f}ms",
            extra={
                "error_info": error_info.to_dict(),
                "duration_ms": duration_ms
            }
        )

        # Re-raise with additional context
        raise ExchangeError(f"{error_info.user_message}: {e}") from e
    else:
        duration_ms = (time.time_ns() - start_time) / 1_000_000
        logger.info(f"Completed {operation} on {exchange_name} in {duration_ms:.2f}ms")


__all__ = [
    "ErrorSeverity",
    "ErrorCategory",
    "ExchangeErrorContext",
    "ExchangeErrorInfo",
    "ExchangeErrorHandler",
    "RetryConfig",
    "ExchangeRetryHandler",
    "CircuitBreakerState",
    "CircuitBreakerConfig",
    "ExchangeCircuitBreaker",
    "exchange_operation_context",
]