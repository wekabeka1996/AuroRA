# -*- coding: utf-8 -*-
"""
Quick validation script for Aurora API service.
"""
import subprocess
import requests
import time
import sys
import os
from pathlib import Path

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


def find_free_port():
    """Find a free port."""
    import socket
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(('', 0))
        s.listen(1)
        port = s.getsockname()[1]
    return port


def test_api_quick():
    """Quick API test without server startup."""
    print("🔍 Testing API imports and configuration...")
    
    try:
        from api.service import app, VERSION
        print(f"✅ FastAPI app imported successfully")
        print(f"📦 App title: {app.title}")
        print(f"🏷️ Version: {VERSION}")
        
        # Test route registration
        routes = [route.path for route in app.routes]
        essential_routes = ["/health", "/version", "/predict", "/pretrade/check"]
        missing = [route for route in essential_routes if route not in routes]
        
        if missing:
            print(f"⚠️ Missing routes: {missing}")
        else:
            print("✅ All essential routes registered")
            
        # Test metrics mount
        mounts = {mount.path: mount.name for mount in app.router.routes if hasattr(mount, 'path') and mount.path.startswith('/metrics')}
        if mounts:
            print(f"✅ Metrics mounted: {mounts}")
        else:
            print("⚠️ Metrics mount not found")
            
        return True
        
    except Exception as e:
        print(f"❌ API import failed: {e}")
        return False


def test_api_with_server():
    """Test API with actual server startup."""
    print("\n🚀 Testing API with server startup...")
    
    port = find_free_port()
    
    # Start server
    cmd = [
        sys.executable, "-m", "uvicorn", 
        "api.service:app", 
        "--host", "127.0.0.1", 
        "--port", str(port),
        "--log-level", "error"
    ]
    
    process = None
    try:
        print(f"📡 Starting server on port {port}...")
        process = subprocess.Popen(
            cmd, 
            cwd=PROJECT_ROOT,
            stdout=subprocess.PIPE, 
            stderr=subprocess.PIPE
        )
        
        # Wait for server to start
        base_url = f"http://127.0.0.1:{port}"
        max_attempts = 30
        
        for attempt in range(max_attempts):
            try:
                response = requests.get(f"{base_url}/health", timeout=2)
                if response.status_code == 200:
                    print("✅ Server started successfully")
                    break
            except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
                time.sleep(0.5)
                if attempt % 5 == 0:
                    print(f"⏳ Waiting for server... ({attempt}/{max_attempts})")
        else:
            raise RuntimeError(f"Server failed to start after {max_attempts} attempts")
        
        # Test endpoints
        tests = [
            ("/health", "Health check"),
            ("/version", "Version info"),
            ("/docs", "API documentation"),
            ("/openapi.json", "OpenAPI schema"),
            ("/metrics", "Prometheus metrics")
        ]
        
        results = []
        for endpoint, description in tests:
            try:
                response = requests.get(f"{base_url}{endpoint}", timeout=5)
                if response.status_code == 200:
                    print(f"✅ {description}: {endpoint}")
                    results.append(True)
                else:
                    print(f"⚠️ {description}: {endpoint} (status: {response.status_code})")
                    results.append(False)
            except Exception as e:
                print(f"❌ {description}: {endpoint} - {e}")
                results.append(False)
        
        success_rate = sum(results) / len(results) * 100
        print(f"\n📊 Endpoint success rate: {success_rate:.1f}% ({sum(results)}/{len(results)})")
        
        return success_rate >= 80
        
    except Exception as e:
        print(f"❌ Server test failed: {e}")
        return False
        
    finally:
        if process:
            print("🛑 Stopping server...")
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()


def main():
    """Run all API tests."""
    print("🧪 Aurora API Validation Suite")
    print("=" * 40)
    
    # Test 1: Import and configuration
    import_ok = test_api_quick()
    
    if not import_ok:
        print("\n❌ Basic tests failed, skipping server tests")
        return False
    
    # Test 2: Server functionality
    server_ok = test_api_with_server()
    
    # Summary
    print("\n" + "=" * 40)
    print("📋 Test Summary:")
    print(f"   🔧 API imports: {'✅ PASS' if import_ok else '❌ FAIL'}")
    print(f"   🚀 Server tests: {'✅ PASS' if server_ok else '❌ FAIL'}")
    
    overall = import_ok and server_ok
    print(f"\n🎯 Overall result: {'✅ ALL TESTS PASSED' if overall else '❌ SOME TESTS FAILED'}")
    
    return overall


if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)