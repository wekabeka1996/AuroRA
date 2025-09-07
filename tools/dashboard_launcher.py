#!/usr/bin/env python3
"""
P3-D Dashboard Launcher
Utility to start React dashboard for Aurora live monitoring.
"""

import argparse
import subprocess
import sys
import os
import shutil
from pathlib import Path
import time

def find_npm():
    """Find npm executable."""
    npm_cmd = 'npm.cmd' if os.name == 'nt' else 'npm'
    if shutil.which(npm_cmd):
        return npm_cmd
    
    # Try alternative locations
    alternatives = ['npm', 'npm.exe'] if os.name == 'nt' else ['npm']
    for alt in alternatives:
        if shutil.which(alt):
            return alt
    
    return None

def install_dependencies(dashboard_dir):
    """Install npm dependencies."""
    npm_cmd = find_npm()
    if not npm_cmd:
        print("❌ npm not found. Please install Node.js and npm first.")
        print("Download from: https://nodejs.org/")
        return False
    
    print("📦 Installing dashboard dependencies...")
    try:
        result = subprocess.run(
            [npm_cmd, 'install'],
            cwd=dashboard_dir,
            check=True,
            capture_output=True,
            text=True
        )
        print("✅ Dependencies installed successfully")
        return True
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install dependencies: {e}")
        if e.stdout:
            print("STDOUT:", e.stdout)
        if e.stderr:
            print("STDERR:", e.stderr)
        return False

def start_dashboard(dashboard_dir, port=3000):
    """Start React development server."""
    npm_cmd = find_npm()
    if not npm_cmd:
        print("❌ npm not found")
        return False
    
    print(f"🚀 Starting dashboard on port {port}...")
    
    # Set environment for React dev server
    env = os.environ.copy()
    env['PORT'] = str(port)
    env['BROWSER'] = 'none'  # Don't auto-open browser
    
    try:
        # Start development server
        process = subprocess.Popen(
            [npm_cmd, 'start'],
            cwd=dashboard_dir,
            env=env
        )
        
        print(f"✅ Dashboard started at http://localhost:{port}")
        print("Press Ctrl+C to stop the dashboard")
        
        # Wait for process
        process.wait()
        
    except KeyboardInterrupt:
        print("\n🛑 Dashboard stopped by user")
        process.terminate()
        return True
    except Exception as e:
        print(f"❌ Failed to start dashboard: {e}")
        return False

def main():
    parser = argparse.ArgumentParser(description='P3-D Dashboard Launcher')
    parser.add_argument('--port', type=int, default=3000,
                        help='Dashboard port (default: 3000)')
    parser.add_argument('--install-only', action='store_true',
                        help='Only install dependencies, do not start')
    parser.add_argument('--telemetry-url', default='http://localhost:8001',
                        help='Telemetry server URL (default: http://localhost:8001)')
    
    args = parser.parse_args()
    
    # Find dashboard directory
    dashboard_dir = Path(__file__).parent / "dashboard"
    if not dashboard_dir.exists():
        print(f"❌ Dashboard directory not found: {dashboard_dir}")
        return 1
    
    # Check package.json
    package_json = dashboard_dir / "package.json"
    if not package_json.exists():
        print(f"❌ package.json not found: {package_json}")
        return 1
    
    print("🎭 Aurora P3-D Live Dashboard Launcher")
    print(f"📁 Dashboard directory: {dashboard_dir}")
    print(f"🔗 Telemetry server: {args.telemetry_url}")
    
    # Install dependencies
    if not install_dependencies(dashboard_dir):
        return 1
    
    if args.install_only:
        print("✅ Dependencies installed. Use --start to launch dashboard.")
        return 0
    
    # Start dashboard
    if not start_dashboard(dashboard_dir, args.port):
        return 1
    
    return 0

if __name__ == "__main__":
    sys.exit(main())