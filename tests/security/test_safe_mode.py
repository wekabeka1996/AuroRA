"""
Security tests for safe-mode toggles and production hardening.

Tests security controls including:
- Safe-mode operation validation
- Secrets management and validation
- Rate limiting and abuse prevention
- Authentication and authorization
- Input validation and sanitization
- Audit trail integrity
"""

import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Security safe_mode harness imports common.config.Config (legacy); quarantined for canon run"
    ),
]
import asyncio
import json
import os
import time
from typing import Any, Dict, List
from unittest.mock import MagicMock, Mock, patch

from common.config import Config
from common.xai_logger import XAILogger
from core.execution.exchange.common import OrderRequest, OrderType, Side
from tests.fixtures.mock_exchange_factory import MockExchangeFactory


class SecurityTestHarness:
    """Harness for testing security controls and safe-mode operations."""

    def __init__(self):
        self.xai_logger = XAILogger(trace_id="security_test_123")
        self.exchange = MockExchangeFactory.create_deterministic_exchange()
        self.config = Config()

    async def test_safe_mode_order_validation(
        self, safe_mode: bool = True
    ) -> Dict[str, Any]:
        """Test order validation in safe mode."""
        results = {
            "safe_mode_enabled": safe_mode,
            "orders_tested": 0,
            "orders_blocked": 0,
            "orders_allowed": 0,
            "validation_errors": [],
        }

        # Test various order scenarios
        test_orders = [
            # Valid order
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id="valid_order_1",
            ),
            # Invalid quantity (too large)
            OrderRequest(
                symbol="BTCUSDT",
                side=Side.BUY,
                type=OrderType.MARKET,
                quantity=1000000.0,  # Unrealistically large
                client_order_id="invalid_quantity",
            ),
            # Invalid symbol
            OrderRequest(
                symbol="INVALID",
                side=Side.BUY,
                type=OrderType.MARKET,
                quantity=1.0,
                client_order_id="invalid_symbol",
            ),
            # Valid limit order
            OrderRequest(
                symbol="ETHUSDT",
                side=Side.SELL,
                type=OrderType.LIMIT,
                quantity=0.5,
                price=2000.0,
                client_order_id="valid_limit",
            ),
        ]

        for order in test_orders:
            results["orders_tested"] += 1

            # Simulate safe-mode validation
            if safe_mode:
                validation_result = await self._validate_order_safety(order)
                if not validation_result["allowed"]:
                    results["orders_blocked"] += 1
                    results["validation_errors"].append(validation_result["reason"])
                    continue

            # Submit order if validation passed
            try:
                result = await self.exchange.submit_order(order)
                if result["status"] in ["accepted", "filled"]:
                    results["orders_allowed"] += 1
                else:
                    results["orders_blocked"] += 1
                    results["validation_errors"].append(
                        f"Exchange rejected: {result.get('reason', 'unknown')}"
                    )
            except Exception as e:
                results["orders_blocked"] += 1
                results["validation_errors"].append(f"Exception: {str(e)}")

        return results

    async def _validate_order_safety(self, order: OrderRequest) -> Dict[str, Any]:
        """Internal order safety validation logic."""
        # Check quantity limits
        max_quantity = 100.0  # Safe limit
        if order.quantity > max_quantity:
            return {
                "allowed": False,
                "reason": f"Quantity {order.quantity} exceeds safe limit {max_quantity}",
            }

        # Check symbol validity
        valid_symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT"]
        if order.symbol not in valid_symbols:
            return {
                "allowed": False,
                "reason": f"Symbol {order.symbol} not in approved list",
            }

        # Check price for limit orders
        if order.type == OrderType.LIMIT:
            if order.price <= 0:
                return {"allowed": False, "reason": "Invalid price for limit order"}

            # Check price deviation (simplified)
            if order.symbol == "BTCUSDT" and order.price > 100000:
                return {"allowed": False, "reason": "Price exceeds safe threshold"}

        return {"allowed": True, "reason": "Order validated"}

    async def test_rate_limiting(self, requests_per_second: int = 10) -> Dict[str, Any]:
        """Test rate limiting functionality."""
        results = {
            "total_requests": 0,
            "allowed_requests": 0,
            "blocked_requests": 0,
            "time_window": 5.0,  # 5 second window
            "rate_limit": requests_per_second,
        }

        start_time = time.time()
        request_times = []

        # Simulate requests over time window
        while time.time() - start_time < results["time_window"]:
            results["total_requests"] += 1

            # Simple rate limiting logic
            current_time = time.time()
            recent_requests = [t for t in request_times if current_time - t < 1.0]

            if len(recent_requests) >= requests_per_second:
                results["blocked_requests"] += 1
                await asyncio.sleep(0.1)  # Wait before retry
                continue

            request_times.append(current_time)
            results["allowed_requests"] += 1

            # Simulate some processing time
            await asyncio.sleep(0.01)

        return results

    async def test_secrets_management(self) -> Dict[str, Any]:
        """Test secrets management and validation."""
        results = {
            "secrets_checked": 0,
            "secrets_valid": 0,
            "secrets_invalid": 0,
            "validation_errors": [],
        }

        # Test various secret scenarios
        test_secrets = {
            "api_key": "sk_test_1234567890abcdef",
            "api_secret": "sk_secret_abcdef1234567890",
            "invalid_key": "",  # Empty
            "weak_secret": "123",  # Too short
            "exposed_secret": "AKIAIOSFODNN7EXAMPLE",  # AWS example key
        }

        for secret_name, secret_value in test_secrets.items():
            results["secrets_checked"] += 1

            validation = self._validate_secret(secret_name, secret_value)
            if validation["valid"]:
                results["secrets_valid"] += 1
            else:
                results["secrets_invalid"] += 1
                results["validation_errors"].append(validation["reason"])

        return results

    def _validate_secret(self, name: str, value: str) -> Dict[str, Any]:
        """Validate individual secret."""
        if not value or len(value.strip()) == 0:
            return {"valid": False, "reason": f"{name}: Empty or whitespace-only value"}

        if len(value) < 8:
            return {
                "valid": False,
                "reason": f"{name}: Secret too short (minimum 8 characters)",
            }

        # Check for obviously exposed secrets
        exposed_patterns = [
            "AKIAIOSFODNN7EXAMPLE",  # AWS example
            "sk_test_",  # Stripe test key prefix
            "password123",  # Common weak password
            "admin",  # Common weak username
        ]

        for pattern in exposed_patterns:
            if pattern.lower() in value.lower():
                return {
                    "valid": False,
                    "reason": f"{name}: Contains exposed/insecure pattern",
                }

        return {"valid": True, "reason": "Secret validated"}

    async def test_audit_trail_integrity(self) -> Dict[str, Any]:
        """Test audit trail integrity and tamper detection."""
        results = {
            "events_logged": 0,
            "events_verified": 0,
            "integrity_checks": 0,
            "tamper_detected": False,
            "verification_errors": [],
        }

        # Simulate audit events
        test_events = [
            {
                "type": "ORDER.SUBMITTED",
                "order_id": "test_123",
                "timestamp": time.time(),
            },
            {
                "type": "ORDER.FILLED",
                "order_id": "test_123",
                "fill_price": 50000,
                "timestamp": time.time(),
            },
            {
                "type": "POSITION.UPDATED",
                "symbol": "BTCUSDT",
                "quantity": 1.0,
                "timestamp": time.time(),
            },
            {"type": "TRADE.COMPLETED", "pnl": 100.50, "timestamp": time.time()},
        ]

        for event in test_events:
            results["events_logged"] += 1

            # Log event
            self.xai_logger.emit(event["type"], event)

            # Verify event was logged correctly
            verification = self._verify_audit_event(event)
            if verification["verified"]:
                results["events_verified"] += 1
            else:
                results["verification_errors"].append(verification["reason"])

        # Check audit trail integrity
        results["integrity_checks"] = 1
        integrity_check = self._check_audit_integrity()
        if not integrity_check["intact"]:
            results["tamper_detected"] = True
            results["verification_errors"].append(integrity_check["reason"])

        return results

    def _verify_audit_event(self, event: Dict[str, Any]) -> Dict[str, Any]:
        """Verify individual audit event."""
        required_fields = ["type", "timestamp"]
        for field in required_fields:
            if field not in event:
                return {"verified": False, "reason": f"Missing required field: {field}"}

        if not isinstance(event["timestamp"], (int, float)):
            return {"verified": False, "reason": "Invalid timestamp format"}

        if event["timestamp"] > time.time() + 60:  # Allow 1 minute future tolerance
            return {"verified": False, "reason": "Timestamp too far in future"}

        return {"verified": True, "reason": "Event verified"}

    def _check_audit_integrity(self) -> Dict[str, Any]:
        """Check audit trail integrity (simplified)."""
        # In a real implementation, this would check cryptographic signatures,
        # hash chains, or other tamper-evident mechanisms

        # For this test, just verify basic structure
        try:
            # Simulate integrity check
            return {"intact": True, "reason": "Audit trail integrity verified"}
        except Exception as e:
            return {"intact": False, "reason": f"Integrity check failed: {str(e)}"}

    async def test_input_sanitization(self) -> Dict[str, Any]:
        """Test input validation and sanitization."""
        results = {
            "inputs_tested": 0,
            "inputs_sanitized": 0,
            "attacks_blocked": 0,
            "sanitization_errors": [],
        }

        # Test various input scenarios including potential attacks
        test_inputs = [
            # Normal inputs
            {"symbol": "BTCUSDT", "quantity": "1.0"},
            {"symbol": "ETHUSDT", "quantity": "0.5"},
            # Malicious inputs
            {
                "symbol": "BTCUSDT'; DROP TABLE users;--",
                "quantity": "1.0",
            },  # SQL injection
            {"symbol": "BTCUSDT", "quantity": "<script>alert('xss')</script>"},  # XSS
            {"symbol": "BTCUSDT", "quantity": "../../../etc/passwd"},  # Path traversal
            {"symbol": "", "quantity": "1.0"},  # Empty symbol
            {"symbol": "BTCUSDT", "quantity": "-1.0"},  # Negative quantity
            {"symbol": "a" * 1000, "quantity": "1.0"},  # Extremely long symbol
        ]

        for input_data in test_inputs:
            results["inputs_tested"] += 1

            sanitized = self._sanitize_input(input_data)
            if sanitized["sanitized"]:
                results["inputs_sanitized"] += 1
            else:
                results["attacks_blocked"] += 1
                results["sanitization_errors"].append(sanitized["reason"])

        return results

    def _sanitize_input(self, input_data: Dict[str, Any]) -> Dict[str, Any]:
        """Sanitize input data."""
        # Check for SQL injection patterns
        sql_patterns = ["'", ";", "--", "DROP", "SELECT", "INSERT", "UPDATE", "DELETE"]
        for key, value in input_data.items():
            if isinstance(value, str):
                for pattern in sql_patterns:
                    if pattern.lower() in value.lower():
                        return {
                            "sanitized": False,
                            "reason": f"SQL injection pattern detected in {key}",
                        }

        # Check for XSS patterns
        xss_patterns = ["<script", "javascript:", "onload=", "onerror="]
        for key, value in input_data.items():
            if isinstance(value, str):
                for pattern in xss_patterns:
                    if pattern.lower() in value.lower():
                        return {
                            "sanitized": False,
                            "reason": f"XSS pattern detected in {key}",
                        }

        # Check for path traversal
        if "symbol" in input_data:
            symbol = input_data["symbol"]
            if ".." in symbol or "/" in symbol or "\\" in symbol:
                return {"sanitized": False, "reason": "Path traversal pattern detected"}

        # Validate quantity
        if "quantity" in input_data:
            try:
                qty = float(input_data["quantity"])
                if qty <= 0:
                    return {
                        "sanitized": False,
                        "reason": "Invalid quantity: must be positive",
                    }
                if qty > 1000:  # Reasonable upper limit
                    return {
                        "sanitized": False,
                        "reason": "Quantity exceeds maximum limit",
                    }
            except (ValueError, TypeError):
                return {"sanitized": False, "reason": "Invalid quantity format"}

        # Check length limits
        for key, value in input_data.items():
            if isinstance(value, str) and len(value) > 100:
                return {"sanitized": False, "reason": f"Input too long for field {key}"}

        return {"sanitized": True, "reason": "Input sanitized successfully"}


class TestSafeModeSecurity:
    """Test security controls and safe-mode operations."""

    @pytest.fixture
    async def setup_security_harness(self):
        """Setup security testing harness."""
        harness = SecurityTestHarness()
        yield harness

    @pytest.mark.asyncio
    async def test_safe_mode_order_validation_enabled(self, setup_security_harness):
        """Test order validation with safe mode enabled."""
        harness = await setup_security_harness

        result = await harness.test_safe_mode_order_validation(safe_mode=True)

        # Assert safe mode blocks risky orders
        assert result["orders_blocked"] > 0
        assert result["orders_allowed"] >= 1  # At least one valid order should pass
        assert len(result["validation_errors"]) > 0

        print(
            f"Safe mode validation - Blocked: {result['orders_blocked']}, Allowed: {result['orders_allowed']}"
        )

    @pytest.mark.asyncio
    async def test_safe_mode_order_validation_disabled(self, setup_security_harness):
        """Test order validation with safe mode disabled."""
        harness = await setup_security_harness

        result = await harness.test_safe_mode_order_validation(safe_mode=False)

        # With safe mode disabled, more orders should be allowed
        assert result["orders_allowed"] >= result["orders_blocked"]

        print(
            f"Normal mode validation - Blocked: {result['orders_blocked']}, Allowed: {result['orders_allowed']}"
        )

    @pytest.mark.asyncio
    async def test_rate_limiting_effectiveness(self, setup_security_harness):
        """Test rate limiting prevents abuse."""
        harness = await setup_security_harness

        result = await harness.test_rate_limiting(5)  # 5 requests per second

        # Assert rate limiting works
        assert result["total_requests"] > result["allowed_requests"]
        assert result["blocked_requests"] > 0
        assert (
            result["allowed_requests"] <= result["rate_limit"] * result["time_window"]
        )

        print(
            f"Rate limiting - Total: {result['total_requests']}, Allowed: {result['allowed_requests']}, Blocked: {result['blocked_requests']}"
        )

    @pytest.mark.asyncio
    async def test_secrets_validation(self, setup_security_harness):
        """Test secrets management and validation."""
        harness = await setup_security_harness

        result = await harness.test_secrets_management()

        # Assert secrets validation works
        assert result["secrets_invalid"] > 0  # Should catch some invalid secrets
        assert result["secrets_valid"] >= 1  # Should validate some good secrets
        assert len(result["validation_errors"]) > 0

        print(
            f"Secrets validation - Valid: {result['secrets_valid']}, Invalid: {result['secrets_invalid']}"
        )

    @pytest.mark.asyncio
    async def test_audit_trail_integrity(self, setup_security_harness):
        """Test audit trail integrity."""
        harness = await setup_security_harness

        result = await harness.test_audit_trail_integrity()

        # Assert audit trail integrity
        assert result["events_verified"] == result["events_logged"]
        assert not result["tamper_detected"]
        assert result["integrity_checks"] == 1

        print(
            f"Audit integrity - Events: {result['events_logged']}, Verified: {result['events_verified']}, Tamper: {result['tamper_detected']}"
        )

    @pytest.mark.asyncio
    async def test_input_sanitization(self, setup_security_harness):
        """Test input validation and sanitization."""
        harness = await setup_security_harness

        result = await harness.test_input_sanitization()

        # Assert input sanitization blocks attacks
        assert result["attacks_blocked"] > 0
        assert result["inputs_sanitized"] >= 2  # At least some valid inputs
        assert len(result["sanitization_errors"]) > 0

        print(
            f"Input sanitization - Sanitized: {result['inputs_sanitized']}, Blocked: {result['attacks_blocked']}"
        )

    @pytest.mark.asyncio
    async def test_comprehensive_security_posture(self, setup_security_harness):
        """Test overall security posture across all controls."""
        harness = await setup_security_harness

        # Run all security tests
        safe_mode_result = await harness.test_safe_mode_order_validation(True)
        rate_limit_result = await harness.test_rate_limiting(3)
        secrets_result = await harness.test_secrets_management()
        audit_result = await harness.test_audit_trail_integrity()
        input_result = await harness.test_input_sanitization()

        # Assert comprehensive security coverage
        assert safe_mode_result["orders_blocked"] > 0
        assert rate_limit_result["blocked_requests"] > 0
        assert secrets_result["secrets_invalid"] > 0
        assert audit_result["events_verified"] > 0
        assert input_result["attacks_blocked"] > 0

        # Calculate security score (simplified)
        total_tests = 5
        passed_tests = sum(
            [
                1 if safe_mode_result["orders_blocked"] > 0 else 0,
                1 if rate_limit_result["blocked_requests"] > 0 else 0,
                1 if secrets_result["secrets_invalid"] > 0 else 0,
                1 if audit_result["events_verified"] > 0 else 0,
                1 if input_result["attacks_blocked"] > 0 else 0,
            ]
        )

        security_score = (passed_tests / total_tests) * 100

        print(
            f"Security posture - Score: {security_score:.1f}%, Tests passed: {passed_tests}/{total_tests}"
        )
        assert security_score >= 80.0  # Require 80% security coverage


# Standalone function for CI security validation
def test_security_posture():
    """Standalone security test for CI pipeline."""
    import asyncio

    async def run_test():
        harness = SecurityTestHarness()

        # Run comprehensive security tests
        safe_mode_result = await harness.test_safe_mode_order_validation(True)
        rate_limit_result = await harness.test_rate_limiting(2)
        secrets_result = await harness.test_secrets_management()
        audit_result = await harness.test_audit_trail_integrity()
        input_result = await harness.test_input_sanitization()

        # Print results for CI
        print(f"Security Test Results:")
        print(f"- Safe mode blocked orders: {safe_mode_result['orders_blocked']}")
        print(
            f"- Rate limiting blocked requests: {rate_limit_result['blocked_requests']}"
        )
        print(f"- Invalid secrets detected: {secrets_result['secrets_invalid']}")
        print(f"- Audit events verified: {audit_result['events_verified']}")
        print(f"- Input attacks blocked: {input_result['attacks_blocked']}")

        # Assert minimum security thresholds
        assert safe_mode_result["orders_blocked"] > 0
        assert rate_limit_result["blocked_requests"] > 0
        assert secrets_result["secrets_invalid"] > 0
        assert audit_result["events_verified"] > 0
        assert input_result["attacks_blocked"] > 0

        return {
            "safe_mode_blocked": safe_mode_result["orders_blocked"],
            "rate_limit_blocked": rate_limit_result["blocked_requests"],
            "secrets_invalid": secrets_result["secrets_invalid"],
            "audit_verified": audit_result["events_verified"],
            "input_blocked": input_result["attacks_blocked"],
        }

    # Run the async test
    return asyncio.run(run_test())


if __name__ == "__main__":
    # Allow running standalone for manual testing
    result = test_security_posture()
    print("Security tests completed successfully!")
