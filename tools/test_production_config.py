#!/usr/bin/env python3
"""
Aurora Production Config System - Final Integration Test
========================================================

Comprehensive test script for the new production configuration system.
"""

import os
import sys
import subprocess
import tempfile
from pathlib import Path

def run_command(cmd, timeout=30):
    """Run command and return result"""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True, timeout=timeout
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", "Command timed out"

def test_config_system():
    """Test the production config system"""
    print("🧪 Testing Aurora Production Configuration System")
    print("=" * 60)
    
    # Set environment
    env = {
        'AURORA_MODE': 'testnet',
        'AURORA_API_TOKEN': 'test_token_1234567890123456'
    }
    
    for key, value in env.items():
        os.environ[key] = value
    
    tests = []
    
    # Test 1: Config CLI validation
    print("\n1. Testing config validation...")
    success, stdout, stderr = run_command("python tools/config_cli.py validate")
    tests.append(("Config Validation", success, stdout if success else stderr))
    
    # Test 2: Config tracing
    print("2. Testing config tracing...")
    success, stdout, stderr = run_command("python tools/config_cli.py trace")
    tests.append(("Config Tracing", success, stdout if success else stderr))
    
    # Test 3: Config hierarchy
    print("3. Testing config hierarchy...")
    success, stdout, stderr = run_command("python tools/config_cli.py hierarchy")
    tests.append(("Config Hierarchy", success, stdout if success else stderr))
    
    # Test 4: API startup test
    print("4. Testing API startup...")
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False, encoding='utf-8') as f:
        f.write("""
import sys
sys.path.insert(0, '.')
from core.config.api_integration import production_lifespan, determine_environment
from fastapi import FastAPI
import asyncio

async def test_api_startup():
    app = FastAPI()
    try:
        async with production_lifespan(app):
            print("API startup successful")
            return True
    except Exception as e:
        print(f"API startup failed: {e}")
        return False

if __name__ == "__main__":
    result = asyncio.run(test_api_startup())
    sys.exit(0 if result else 1)
""")
        temp_script = f.name
    
    try:
        success, stdout, stderr = run_command(f"python {temp_script}", timeout=15)
        tests.append(("API Startup", success, stdout if success else stderr))
    finally:
        os.unlink(temp_script)
    
    # Results
    print("\n" + "=" * 60)
    print("🎯 TEST RESULTS")
    print("=" * 60)
    
    passed = 0
    for test_name, success, output in tests:
        status = "✅ PASS" if success else "❌ FAIL"
        print(f"{status} {test_name}")
        if not success:
            print(f"    Error: {output[:200]}...")
        else:
            passed += 1
    
    print(f"\n📊 Summary: {passed}/{len(tests)} tests passed")
    
    if passed == len(tests):
        print("\n🎉 ALL TESTS PASSED - Production config system is ready!")
        return True
    else:
        print(f"\n⚠️  {len(tests) - passed} tests failed - review errors above")
        return False

if __name__ == "__main__":
    success = test_config_system()
    sys.exit(0 if success else 1)