#!/usr/bin/env python3
"""
Aurora Testnet System Diagnostics
Comprehensive test suite to validate all system components
"""

import os
import sys
import json
import time
import subprocess
import requests
from pathlib import Path
from typing import Dict, List, Tuple, Optional

class AuroraDiagnostics:
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent
        self.api_url = "http://127.0.0.1:8080"
        self.metrics_url = "http://127.0.0.1:9100"
        self.results = []
        
    def log_result(self, test_name: str, status: str, details: str = ""):
        """Log test result"""
        result = {
            "test": test_name,
            "status": status,  # PASS, FAIL, WARN, SKIP
            "details": details,
            "timestamp": time.time()
        }
        self.results.append(result)
        
        # Color output
        color = {
            "PASS": "\033[92m✅",
            "FAIL": "\033[91m❌", 
            "WARN": "\033[93m⚠️",
            "SKIP": "\033[94mℹ️"
        }.get(status, "")
        
        print(f"{color} {test_name}: {status}\033[0m")
        if details:
            print(f"   → {details}")
    
    def test_environment_config(self) -> bool:
        """Test 1: Environment Configuration"""
        try:
            env_file = self.base_dir / ".env"
            if not env_file.exists():
                self.log_result("Environment Config", "FAIL", "Missing .env file")
                return False
                
            with open(env_file) as f:
                env_content = f.read()
            
            required_vars = [
                "BINANCE_ENV=testnet",
                "AURORA_MODE=testnet", 
                "BINANCE_API_KEY=",
                "BINANCE_API_SECRET=",
                "EXCHANGE_TESTNET=true",
                "DRY_RUN=false"
            ]
            
            missing = []
            for var in required_vars:
                if var not in env_content:
                    missing.append(var)
            
            if missing:
                self.log_result("Environment Config", "FAIL", f"Missing: {', '.join(missing)}")
                return False
            
            self.log_result("Environment Config", "PASS", "All required variables present")
            return True
            
        except Exception as e:
            self.log_result("Environment Config", "FAIL", str(e))
            return False
    
    def test_config_files(self) -> bool:
        """Test 2: Configuration Files"""
        try:
            testnet_config = self.base_dir / "configs" / "aurora" / "testnet.yaml"
            if not testnet_config.exists():
                self.log_result("Config Files", "FAIL", "Missing testnet.yaml")
                return False
            
            # Check overlay config
            overlay_config = self.base_dir / "profiles" / "overlays" / "_active_shadow.yaml"
            if not overlay_config.exists():
                self.log_result("Config Files", "WARN", "Missing overlay config")
            
            self.log_result("Config Files", "PASS", "Required configs present")
            return True
            
        except Exception as e:
            self.log_result("Config Files", "FAIL", str(e))
            return False
    
    def test_port_availability(self) -> bool:
        """Test 3: Port Availability"""
        try:
            # Test if ports are free
            import socket
            ports = [8080, 9100]
            busy_ports = []
            
            for port in ports:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(1)
                result = sock.connect_ex(('127.0.0.1', port))
                sock.close()
                
                if result == 0:
                    busy_ports.append(port)
            
            if busy_ports:
                self.log_result("Port Availability", "FAIL", f"Ports busy: {busy_ports}")
                return False
            
            self.log_result("Port Availability", "PASS", "Ports 8080, 9100 available")
            return True
            
        except Exception as e:
            self.log_result("Port Availability", "FAIL", str(e))
            return False
    
    def test_binance_connectivity(self) -> bool:
        """Test 4: Binance Testnet Connectivity"""
        try:
            testnet_url = "https://testnet.binancefuture.com/fapi/v1/ping"
            response = requests.get(testnet_url, timeout=5)
            
            if response.status_code == 200:
                self.log_result("Binance Connectivity", "PASS", "Testnet reachable")
                return True
            else:
                self.log_result("Binance Connectivity", "FAIL", f"Status: {response.status_code}")
                return False
                
        except Exception as e:
            self.log_result("Binance Connectivity", "FAIL", str(e))
            return False
    
    def test_api_startup(self) -> Tuple[bool, Optional[subprocess.Popen]]:
        """Test 5: API Startup"""
        try:
            # Start API process
            env = os.environ.copy()
            env.update({
                "AURORA_MODE": "testnet",
                "AURORA_API_TOKEN": "accept_testnet_token_123456789", 
                "AURORA_OPS_TOKEN": "aurora_dev_ops_token_abcdef0123456789"
            })
            
            api_proc = subprocess.Popen([
                sys.executable, "-m", "uvicorn", 
                "api.service:app",
                "--host", "127.0.0.1",
                "--port", "8080",
                "--workers", "1"
            ], cwd=self.base_dir, env=env, 
               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait for startup
            time.sleep(8)
            
            # Test health endpoint
            try:
                response = requests.get(f"{self.api_url}/health", timeout=5)
                if response.status_code == 200:
                    health_data = response.json()
                    status = health_data.get("status", "unknown")
                    
                    if status in ["ok", "starting"]:
                        self.log_result("API Startup", "PASS", f"Status: {status}")
                        return True, api_proc
                    else:
                        self.log_result("API Startup", "WARN", f"Status: {status}")
                        return True, api_proc
                else:
                    self.log_result("API Startup", "FAIL", f"HTTP {response.status_code}")
                    api_proc.terminate()
                    return False, None
                    
            except requests.exceptions.RequestException as e:
                self.log_result("API Startup", "FAIL", f"Connection failed: {e}")
                api_proc.terminate()
                return False, None
                
        except Exception as e:
            self.log_result("API Startup", "FAIL", str(e))
            return False, None
    
    def test_runner_startup(self) -> Tuple[bool, Optional[subprocess.Popen]]:
        """Test 6: Runner Startup"""
        try:
            env = os.environ.copy()
            env.update({
                "AURORA_MODE": "testnet",
                "DRY_RUN": "false"
            })
            
            runner_proc = subprocess.Popen([
                sys.executable, "-m", "skalp_bot.runner.run_live_aurora",
                "--config", "configs/aurora/testnet.yaml"
            ], cwd=self.base_dir, env=env,
               stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            
            # Wait for initialization
            time.sleep(10)
            
            # Check if process is still running
            if runner_proc.poll() is None:
                self.log_result("Runner Startup", "PASS", "Process running")
                return True, runner_proc
            else:
                stdout, stderr = runner_proc.communicate()
                error_msg = stderr.decode()[:200] if stderr else "Process exited"
                self.log_result("Runner Startup", "FAIL", error_msg)
                return False, None
                
        except Exception as e:
            self.log_result("Runner Startup", "FAIL", str(e))
            return False, None
    
    def test_event_logging(self) -> bool:
        """Test 7: Event Logging"""
        try:
            session_dir = self.base_dir / "logs" / "testnet_session"
            if not session_dir.exists():
                self.log_result("Event Logging", "FAIL", "Session directory missing")
                return False
            
            events_file = session_dir / "aurora_events.jsonl"
            if not events_file.exists():
                self.log_result("Event Logging", "FAIL", "Events file missing")
                return False
            
            # Check recent events
            with open(events_file) as f:
                lines = f.readlines()
            
            if len(lines) < 5:
                self.log_result("Event Logging", "WARN", f"Only {len(lines)} events")
                return True
            
            # Parse last few events
            recent_events = []
            for line in lines[-10:]:
                try:
                    event = json.loads(line.strip())
                    recent_events.append(event.get("type", "UNKNOWN"))
                except:
                    continue
            
            if recent_events:
                self.log_result("Event Logging", "PASS", f"Recent: {', '.join(recent_events[-3:])}")
                return True
            else:
                self.log_result("Event Logging", "WARN", "No valid events found")
                return True
                
        except Exception as e:
            self.log_result("Event Logging", "FAIL", str(e))
            return False
    
    def test_metrics_export(self) -> bool:
        """Test 8: Metrics Export"""
        try:
            response = requests.get(f"{self.metrics_url}/metrics", timeout=5)
            if response.status_code == 200:
                metrics = response.text
                if "sse_clients_connected" in metrics:
                    self.log_result("Metrics Export", "PASS", "Prometheus metrics available")
                    return True
                else:
                    self.log_result("Metrics Export", "WARN", "Limited metrics")
                    return True
            else:
                self.log_result("Metrics Export", "FAIL", f"HTTP {response.status_code}")
                return False
                
        except Exception as e:
            self.log_result("Metrics Export", "FAIL", str(e))
            return False
    
    def cleanup_processes(self, api_proc=None, runner_proc=None):
        """Cleanup test processes"""
        print("\n🧹 Cleaning up test processes...")
        
        if api_proc:
            api_proc.terminate()
            api_proc.wait(timeout=5)
            
        if runner_proc:
            runner_proc.terminate()
            runner_proc.wait(timeout=5)
    
    def generate_report(self):
        """Generate diagnostic report"""
        print("\n" + "="*60)
        print("🔍 AURORA TESTNET DIAGNOSTICS REPORT")
        print("="*60)
        
        total_tests = len(self.results)
        passed = len([r for r in self.results if r["status"] == "PASS"])
        failed = len([r for r in self.results if r["status"] == "FAIL"])
        warnings = len([r for r in self.results if r["status"] == "WARN"])
        
        print(f"📊 Summary: {passed}/{total_tests} tests passed")
        print(f"   ✅ Passed: {passed}")
        print(f"   ❌ Failed: {failed}")
        print(f"   ⚠️  Warnings: {warnings}")
        
        if failed == 0:
            print("\n🎉 System ready for testnet operation!")
        else:
            print(f"\n🚨 {failed} critical issues found:")
            for result in self.results:
                if result["status"] == "FAIL":
                    print(f"   • {result['test']}: {result['details']}")
        
        # Save detailed report
        report_file = self.base_dir / "artifacts" / "diagnostics_report.json"
        report_file.parent.mkdir(exist_ok=True)
        
        with open(report_file, 'w') as f:
            json.dump({
                "timestamp": time.time(),
                "summary": {
                    "total": total_tests,
                    "passed": passed,
                    "failed": failed,
                    "warnings": warnings
                },
                "results": self.results
            }, f, indent=2)
        
        print(f"\n📄 Detailed report: {report_file}")
    
    def run_full_diagnostics(self):
        """Run complete diagnostic suite"""
        print("🔍 Starting Aurora Testnet Diagnostics...\n")
        
        # Phase 1: Pre-flight checks
        self.test_environment_config()
        self.test_config_files()
        self.test_port_availability()
        self.test_binance_connectivity()
        
        # Phase 2: System startup
        api_success, api_proc = self.test_api_startup()
        runner_success, runner_proc = self.test_runner_startup() if api_success else (False, None)
        
        # Phase 3: Runtime checks
        if api_success and runner_success:
            time.sleep(5)  # Let system stabilize
            self.test_event_logging()
            self.test_metrics_export()
        
        # Cleanup
        self.cleanup_processes(api_proc, runner_proc)
        
        # Report
        self.generate_report()

if __name__ == "__main__":
    diagnostics = AuroraDiagnostics()
    diagnostics.run_full_diagnostics()