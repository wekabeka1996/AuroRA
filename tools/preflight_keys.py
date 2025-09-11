#!/usr/bin/env python3
"""
Preflight Exchange Keys Validation
==================================

Validates exchange API keys with basic connectivity and permission checks.
Performs lightweight validation without affecting account state.

Usage:
    python tools/preflight_keys.py --exchange binance_testnet_futures
    python tools/preflight_keys.py --all
"""

import asyncio
import json
import logging
import sys
import time
from argparse import ArgumentParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple

import aiohttp

from core.execution.exchange.config import get_config_manager
from core.execution.exchange.unified import ExchangeType

logger = logging.getLogger(__name__)


class PreflightValidator:
    """Validates exchange connectivity and permissions."""

    def __init__(self, exchange_name: str):
        self.exchange_name = exchange_name
        self.config_manager = get_config_manager()
        self.config = self.config_manager.get_config(exchange_name)
        if not self.config:
            raise ValueError(f"Exchange config not found: {exchange_name}")

    async def validate_connectivity(self) -> Tuple[bool, Dict]:
        """Test basic connectivity and latency."""
        results = {
            "exchange": self.exchange_name,
            "connectivity": False,
            "latency_ms": None,
            "server_time": None,
            "error": None,
        }

        try:
            start_time = time.time()

            if self.config.settings.type == ExchangeType.BINANCE:
                url = f"{self.config.settings.base_url}/fapi/v1/time"
            else:
                results["error"] = (
                    f"Unsupported exchange type: {self.config.settings.type}"
                )
                return False, results

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=10)
                ) as response:
                    latency_ms = (time.time() - start_time) * 1000

                    if response.status == 200:
                        data = await response.json()
                        results.update(
                            {
                                "connectivity": True,
                                "latency_ms": round(latency_ms, 2),
                                "server_time": data.get("serverTime"),
                            }
                        )

                        if latency_ms > 200:
                            results["warning"] = f"High latency: {latency_ms:.1f}ms"

                        return True, results
                    else:
                        results["error"] = (
                            f"HTTP {response.status}: {await response.text()}"
                        )
                        return False, results

        except Exception as e:
            results["error"] = str(e)
            return False, results

    async def validate_exchange_info(self) -> Tuple[bool, Dict]:
        """Validate exchange info and symbol availability."""
        results = {
            "exchange_info": False,
            "symbols_found": [],
            "symbols_missing": [],
            "error": None,
        }

        try:
            if self.config.settings.type == ExchangeType.BINANCE:
                url = f"{self.config.settings.base_url}/fapi/v1/exchangeInfo"
            else:
                results["error"] = (
                    f"Unsupported exchange type: {self.config.settings.type}"
                )
                return False, results

            target_symbols = ["BTCUSDT", "ETHUSDT", "ADAUSDT", "SOLUSDT"]

            async with aiohttp.ClientSession() as session:
                async with session.get(
                    url, timeout=aiohttp.ClientTimeout(total=15)
                ) as response:
                    if response.status == 200:
                        data = await response.json()
                        available_symbols = {
                            s["symbol"] for s in data.get("symbols", [])
                        }

                        for symbol in target_symbols:
                            if symbol in available_symbols:
                                results["symbols_found"].append(symbol)
                            else:
                                results["symbols_missing"].append(symbol)

                        results["exchange_info"] = len(results["symbols_missing"]) == 0
                        return results["exchange_info"], results
                    else:
                        results["error"] = (
                            f"HTTP {response.status}: {await response.text()}"
                        )
                        return False, results

        except Exception as e:
            results["error"] = str(e)
            return False, results

    async def validate_credentials(self) -> Tuple[bool, Dict]:
        """Test API credentials with minimal permissions check."""
        results = {"credentials": False, "permissions": [], "error": None}

        if (
            not self.config.credentials.api_key
            or not self.config.credentials.api_secret
        ):
            results["error"] = "Missing API key or secret"
            return False, results

        try:
            # Test with invalid order ID to check auth without side effects
            if self.config.settings.type == ExchangeType.BINANCE:
                import hashlib
                import hmac
                from urllib.parse import urlencode

                url = f"{self.config.settings.base_url}/fapi/v1/order"
                timestamp = int(time.time() * 1000)
                params = {
                    "symbol": "BTCUSDT",
                    "orderId": 999999999,  # Non-existent order ID
                    "timestamp": timestamp,
                    "recvWindow": self.config.settings.recv_window_ms,
                }

                query_string = urlencode(params)
                signature = hmac.new(
                    self.config.credentials.api_secret.encode(),
                    query_string.encode(),
                    hashlib.sha256,
                ).hexdigest()

                params["signature"] = signature

                headers = {"X-MBX-APIKEY": self.config.credentials.api_key}

                async with aiohttp.ClientSession() as session:
                    async with session.get(
                        url,
                        params=params,
                        headers=headers,
                        timeout=aiohttp.ClientTimeout(total=10),
                    ) as response:
                        response_text = await response.text()

                        if response.status == 400:
                            # Expected: Invalid order ID, but auth worked
                            try:
                                error_data = json.loads(response_text)
                                if (
                                    error_data.get("code") == -2013
                                ):  # Order does not exist
                                    results["credentials"] = True
                                    results["permissions"] = ["read_orders"]
                                    return True, results
                            except json.JSONDecodeError:
                                pass

                        if response.status == 401:
                            results["error"] = "Invalid API key or signature"
                        elif response.status == 403:
                            results["error"] = "API key lacks required permissions"
                        else:
                            results["error"] = (
                                f"HTTP {response.status}: {response_text}"
                            )

                        return False, results
            else:
                results["error"] = (
                    f"Credential validation not implemented for {self.config.settings.type}"
                )
                return False, results

        except Exception as e:
            results["error"] = str(e)
            return False, results

    async def run_all_checks(self) -> Dict:
        """Run all preflight checks."""
        print(f"🔍 Running preflight checks for {self.exchange_name}...")

        all_results = {
            "exchange": self.exchange_name,
            "timestamp": time.time(),
            "overall_status": "UNKNOWN",
            "checks": {},
        }

        # Connectivity check
        print("  ├─ Testing connectivity...")
        connectivity_ok, connectivity_results = await self.validate_connectivity()
        all_results["checks"]["connectivity"] = connectivity_results

        if connectivity_ok:
            print(f"  ├─ ✅ Connectivity OK ({connectivity_results['latency_ms']}ms)")
        else:
            print(f"  ├─ ❌ Connectivity FAILED: {connectivity_results['error']}")
            all_results["overall_status"] = "FAILED"
            return all_results

        # Exchange info check
        print("  ├─ Testing exchange info...")
        info_ok, info_results = await self.validate_exchange_info()
        all_results["checks"]["exchange_info"] = info_results

        if info_ok:
            print(
                f"  ├─ ✅ Exchange info OK ({len(info_results['symbols_found'])} symbols)"
            )
        else:
            print(
                f"  ├─ ⚠️  Exchange info issues: {info_results['error'] or 'Missing symbols'}"
            )

        # Credentials check
        print("  ├─ Testing credentials...")
        creds_ok, creds_results = await self.validate_credentials()
        all_results["checks"]["credentials"] = creds_results

        if creds_ok:
            print(f"  └─ ✅ Credentials OK")
            all_results["overall_status"] = "PASSED"
        else:
            print(f"  └─ ❌ Credentials FAILED: {creds_results['error']}")
            all_results["overall_status"] = "FAILED"

        return all_results


async def main():
    parser = ArgumentParser(description="Preflight validation for exchange API keys")
    parser.add_argument("--exchange", help="Exchange name to validate")
    parser.add_argument(
        "--all", action="store_true", help="Validate all configured exchanges"
    )
    parser.add_argument("--output", help="Output file for results (JSON)")
    parser.add_argument("--verbose", "-v", action="store_true", help="Verbose logging")

    args = parser.parse_args()

    if args.verbose:
        logging.basicConfig(level=logging.DEBUG)
    else:
        logging.basicConfig(level=logging.WARNING)

    config_manager = get_config_manager()

    if args.all:
        exchange_names = config_manager.list_configs()
    elif args.exchange:
        exchange_names = [args.exchange]
    else:
        print("❌ Please specify --exchange <name> or --all")
        sys.exit(1)

    if not exchange_names:
        print("❌ No exchange configurations found")
        sys.exit(1)

    all_results = []
    overall_success = True

    for exchange_name in exchange_names:
        try:
            validator = PreflightValidator(exchange_name)
            results = await validator.run_all_checks()
            all_results.append(results)

            if results["overall_status"] != "PASSED":
                overall_success = False

        except Exception as e:
            print(f"❌ Failed to validate {exchange_name}: {e}")
            overall_success = False
            all_results.append(
                {"exchange": exchange_name, "overall_status": "ERROR", "error": str(e)}
            )

    # Output results
    if args.output:
        with open(args.output, "w") as f:
            json.dump(all_results, f, indent=2)
        print(f"📄 Results saved to {args.output}")

    # Summary
    print(f"\n📊 Preflight Summary:")
    passed = sum(1 for r in all_results if r.get("overall_status") == "PASSED")
    print(f"  ✅ Passed: {passed}/{len(all_results)}")

    if overall_success:
        print("🎉 All preflight checks PASSED")
        sys.exit(0)
    else:
        print("❌ Some preflight checks FAILED")
        sys.exit(1)


if __name__ == "__main__":
    asyncio.run(main())
