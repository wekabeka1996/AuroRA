#!/usr/bin/env python3
"""
Profile Lock Generator v1.0 - Definitive Lock Mechanism
Creates SHA256-based locks for configuration profiles
"""
import json
import yaml
import hashlib
import argparse
from pathlib import Path
from datetime import datetime
from typing import Optional

def normalize_yaml_for_hash(yaml_content: dict) -> str:
    """Normalize YAML for consistent hashing"""
    # Sort keys recursively and format consistently
    return json.dumps(yaml_content, sort_keys=True, separators=(',', ':'))

def calculate_profile_hash(profile_path: Path) -> str:
    """Calculate SHA256 hash of normalized profile"""
    with open(profile_path, 'r', encoding='utf-8') as f:
        profile_data = yaml.safe_load(f)
    
    normalized = normalize_yaml_for_hash(profile_data)
    return hashlib.sha256(normalized.encode('utf-8')).hexdigest()

def create_profile_lock(profile_path: Path, output_path: Optional[Path] = None) -> Path:
    """Create lock file for profile"""
    if output_path is None:
        output_path = profile_path.with_suffix('.lock.json')
    
    profile_hash = calculate_profile_hash(profile_path)
    
    lock_data = {
        "schema_v": 1,
        "profile_name": profile_path.stem,
        "profile_path": str(profile_path),
        "sha256_normalized_yaml": profile_hash,
        "generated_at": datetime.now().isoformat(),
        "generator_ver": "1.0"
    }
    
    with open(output_path, 'w') as f:
        json.dump(lock_data, f, indent=2)
    
    print(f"🔒 Profile lock created: {output_path}")
    print(f"   Profile: {profile_path}")
    print(f"   SHA256: {profile_hash}")
    
    return output_path

def validate_profile_lock(profile_path: Path, lock_path: Path) -> tuple[bool, str]:
    """Validate profile against its lock"""
    if not lock_path.exists():
        return False, f"Lock file not found: {lock_path}"
    
    try:
        # Load lock data
        with open(lock_path, 'r') as f:
            lock_data = json.load(f)
        
        # Calculate current profile hash
        current_hash = calculate_profile_hash(profile_path)
        expected_hash = lock_data.get('sha256_normalized_yaml', '')
        
        if current_hash == expected_hash:
            return True, f"Profile hash matches: {current_hash[:16]}..."
        else:
            return False, f"Hash mismatch: current={current_hash[:16]}... expected={expected_hash[:16]}..."
    
    except Exception as e:
        return False, f"Validation error: {e}"

def main():
    parser = argparse.ArgumentParser(description="Profile Lock Generator v1.0")
    parser.add_argument("--in", dest="input_profile", required=True,
                       help="Input profile YAML file")
    parser.add_argument("--out", dest="output_lock",
                       help="Output lock JSON file (default: <profile>.lock.json)")
    parser.add_argument("--validate", action="store_true",
                       help="Validate existing lock instead of creating new one")
    parser.add_argument("--dry-run", action="store_true",
                       help="Show what would be done without creating files")
    
    args = parser.parse_args()
    
    profile_path = Path(args.input_profile)
    
    if not profile_path.exists():
        print(f"❌ Profile not found: {profile_path}")
        return 2
    
    if args.output_lock:
        lock_path = Path(args.output_lock)
    else:
        lock_path = profile_path.with_suffix('.lock.json')
    
    if args.validate:
        # Validate mode
        valid, message = validate_profile_lock(profile_path, lock_path)
        
        if valid:
            print(f"✅ Profile lock valid: {message}")
            return 0
        else:
            print(f"❌ Profile lock invalid: {message}")
            return 3
    
    else:
        # Create mode
        if args.dry_run:
            profile_hash = calculate_profile_hash(profile_path)
            print(f"🔍 Dry run mode:")
            print(f"   Would create: {lock_path}")
            print(f"   Profile hash: {profile_hash}")
            return 2
        
        create_profile_lock(profile_path, lock_path)
        return 0

if __name__ == "__main__":
    exit(main())