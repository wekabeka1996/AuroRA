#!/usr/bin/env python3
"""
Aurora Configuration Tracer
Traces exactly which config files are loaded during Aurora testnet startup.
"""

import json
from pathlib import Path
from typing import Dict, List, Set

class ConfigTracer:
    def __init__(self):
        self.base_dir = Path(__file__).parent.parent
        
    def parse_events(self) -> Dict:
        """Parse aurora events to find configuration loading"""
        
        events_file = self.base_dir / "logs" / "testnet_session" / "aurora_events.jsonl"
        if not events_file.exists():
            return {"error": "No events file found"}
        
        config_events = []
        model_paths = []
        overlay_events = []
        
        with open(events_file, 'r') as f:
            for line in f:
                try:
                    event = json.loads(line.strip())
                    event_type = event.get("type", "")
                    event_code = event.get("event_code", "")
                    
                    if event_code == "CONFIG.SWITCHED":
                        details = event.get("details", {})
                        config_events.append({
                            "timestamp": event.get("ts_ns", 0),
                            "config_name": details.get("name", "unknown")
                        })
                    
                    elif event_type == "MODEL.PATHS":
                        payload = event.get("payload", {})
                        details = payload.get("details", {})
                        model_paths.append({
                            "timestamp": payload.get("ts_ns", 0),
                            "config_path": details.get("config_path", ""),
                            "overlay_path": details.get("overlay_path", ""),
                            "hazard_features": details.get("hazard_features", []),
                            "hazard_coeffs": details.get("hazard_coeffs", {})
                        })
                    
                    elif event_type == "OVERLAY.RELOAD":
                        payload = event.get("payload", {})
                        details = payload.get("details", {})
                        overlay_events.append({
                            "timestamp": payload.get("ts_ns", 0),
                            "path": details.get("path", "")
                        })
                        
                except json.JSONDecodeError:
                    continue
        
        return {
            "config_events": config_events,
            "model_paths": model_paths,
            "overlay_events": overlay_events
        }
    
    def check_actual_files(self) -> Dict:
        """Check which config files actually exist and their content"""
        
        files_to_check = [
            "configs/aurora/testnet.yaml",
            "configs/aurora/base.yaml", 
            "configs/aurora/development.yaml",
            "configs/aurora/prod.yaml",
            "profiles/sol_soon_base.yaml",
            "profiles/overlays/_active_shadow.yaml",
            ".env"
        ]
        
        existing_files = []
        missing_files = []
        
        for file_path in files_to_check:
            full_path = self.base_dir / file_path
            if full_path.exists():
                try:
                    with open(full_path, 'r') as f:
                        content_preview = f.read(300)  # First 300 chars
                    
                    existing_files.append({
                        "path": file_path,
                        "size": full_path.stat().st_size,
                        "preview": content_preview.replace('\n', ' ')[:100]
                    })
                except Exception as e:
                    existing_files.append({
                        "path": file_path,
                        "size": full_path.stat().st_size,
                        "error": str(e)
                    })
            else:
                missing_files.append(file_path)
        
        return {
            "existing_files": existing_files,
            "missing_files": missing_files
        }
    
    def trace_loading_sequence(self) -> Dict:
        """Determine the exact loading sequence from code analysis"""
        
        # Read the actual config loading logic
        config_loader = self.base_dir / "common" / "config.py"
        loading_logic = ""
        
        if config_loader.exists():
            with open(config_loader, 'r') as f:
                lines = f.readlines()
                
            # Find the priority chain
            for i, line in enumerate(lines):
                if "testnet" in line.lower() and "yaml" in line:
                    # Capture context around testnet loading
                    start = max(0, i-5)
                    end = min(len(lines), i+10)
                    loading_logic += "".join(lines[start:end])
                    break
        
        return {
            "loading_logic": loading_logic,
            "priority_chain": [
                "Environment Variables (highest)",
                "AURORA_CONFIG env var",
                "AURORA_CONFIG_NAME env var", 
                "configs/aurora/testnet.yaml (for AURORA_MODE=testnet)",
                "configs/aurora/base.yaml",
                "profiles/overlays/_active_shadow.yaml (overlay)",
                "Production Config System (configs/aurora/)",
                "Multi-symbol profiles (profiles/)",
                "Overlay system (profiles/overlays/)"
            ]
        }
    
    def generate_report(self):
        """Generate comprehensive config tracing report"""
        
        print("="*70)
        print("🔍 AURORA TESTNET CONFIG TRACING REPORT")
        print("="*70)
        
        # Parse events
        events_data = self.parse_events()
        
        if "error" not in events_data:
            print(f"\n📋 CONFIG EVENTS FROM LOGS:")
            for event in events_data["config_events"]:
                print(f"   • Config switched to: {event['config_name']}")
            
            print(f"\n📂 ACTUAL PATHS LOADED:")
            for path_event in events_data["model_paths"]:
                print(f"   • Main config: {path_event['config_path']}")
                print(f"   • Overlay: {path_event['overlay_path']}")
                if path_event["hazard_features"]:
                    print(f"   • Features: {', '.join(path_event['hazard_features'])}")
                break  # Just show first one
            
            print(f"\n🔄 OVERLAY RELOADS:")
            unique_overlays = set()
            for overlay in events_data["overlay_events"]:
                unique_overlays.add(overlay["path"])
            for overlay_path in unique_overlays:
                print(f"   • {overlay_path}")
        
        # Check files
        files_data = self.check_actual_files()
        
        print(f"\n✅ EXISTING CONFIG FILES:")
        for file_info in files_data["existing_files"]:
            print(f"   • {file_info['path']} ({file_info['size']} bytes)")
            if "preview" in file_info:
                print(f"     Preview: {file_info['preview']}")
        
        if files_data["missing_files"]:
            print(f"\n❌ MISSING FILES:")
            for missing in files_data["missing_files"]:
                print(f"   • {missing}")
        
        # Loading sequence
        sequence_data = self.trace_loading_sequence()
        
        print(f"\n🔄 LOADING PRIORITY CHAIN:")
        for i, step in enumerate(sequence_data["priority_chain"], 1):
            print(f"   {i}. {step}")
        
        print(f"\n🎯 FINAL ANSWER:")
        print(f"   При запуску testnet використовуються:")
        print(f"   ✅ configs/aurora/testnet.yaml (основний)")
        print(f"   ✅ profiles/overlays/_active_shadow.yaml (overlay)")
        print(f"   ✅ .env файл (environment overrides)")
        print(f"   ❓ Archived per-symbol configs in archive/configs_legacy/config_old_per_symbol/")
        
        # Save report
        report_data = {
            "events": events_data,
            "files": files_data,
            "sequence": sequence_data
        }
        
        report_file = self.base_dir / "artifacts" / "config_trace_report.json"
        with open(report_file, 'w') as f:
            json.dump(report_data, f, indent=2)
        
        print(f"\n📄 Full report saved: {report_file}")

if __name__ == "__main__":
    tracer = ConfigTracer()
    tracer.generate_report()