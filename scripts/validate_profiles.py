#!/usr/bin/env python3
"""
Configuration Profile Validator
Перевіряє та блокує профілі конфігурації
"""
import os
import yaml
import json
import argparse
from pathlib import Path
import hashlib
from dataclasses import dataclass
from typing import Dict, Any, List

@dataclass
class ProfileValidation:
    profile_name: str
    is_valid: bool
    errors: List[str]
    warnings: List[str]
    checksum: str

def load_yaml_config(config_path):
    """Завантажити YAML конфігурацію"""
    try:
        with open(config_path, 'r') as f:
            return yaml.safe_load(f)
    except Exception as e:
        raise Exception(f"Failed to load {config_path}: {e}")

def calculate_config_checksum(config_dict):
    """Обчислити checksum конфігурації"""
    config_str = json.dumps(config_dict, sort_keys=True)
    return hashlib.sha256(config_str.encode()).hexdigest()[:16]

def validate_profile_structure(config, profile_name):
    """Валідувати структуру профілю"""
    errors = []
    warnings = []
    
    # Обов'язкові секції
    required_sections = ["acceptance", "kappa_thresholds", "preloop"]
    for section in required_sections:
        if section not in config:
            errors.append(f"Missing required section: {section}")
    
    # Перевірити acceptance параметри
    if "acceptance" in config:
        acceptance = config["acceptance"]
        
        if "coverage_target" not in acceptance:
            errors.append("Missing acceptance.coverage_target")
        elif not 0.0 <= acceptance["coverage_target"] <= 1.0:
            errors.append("acceptance.coverage_target must be between 0.0 and 1.0")
        
        if "min_decisions" not in acceptance:
            warnings.append("Missing acceptance.min_decisions (recommended)")
    
    # Перевірити kappa_thresholds
    if "kappa_thresholds" in config:
        thresholds = config["kappa_thresholds"]
        
        required_thresholds = ["tau_d", "tau_p"]
        for threshold in required_thresholds:
            if threshold not in thresholds:
                errors.append(f"Missing kappa_thresholds.{threshold}")
            elif not 0.0 <= thresholds[threshold] <= 1.0:
                errors.append(f"kappa_thresholds.{threshold} must be between 0.0 and 1.0")
    
    # Перевірити preloop параметри
    if "preloop" in config:
        preloop = config["preloop"]
        
        if "max_noop_ratio" not in preloop:
            errors.append("Missing preloop.max_noop_ratio")
        elif not 0.0 <= preloop["max_noop_ratio"] <= 1.0:
            errors.append("preloop.max_noop_ratio must be between 0.0 and 1.0")
        
        # Специфічні перевірки для різних профілів
        if profile_name == "r2" and preloop.get("max_noop_ratio", 1.0) > 0.7:
            warnings.append("Production profile should have stricter max_noop_ratio")
        
        if profile_name == "smoke" and "require_trigger" in preloop:
            if preloop["require_trigger"] != False:
                warnings.append("Smoke profile should have require_trigger: false")
    
    return errors, warnings

def validate_profile_consistency(profiles):
    """Перевірити консистентність між профілями"""
    warnings = []
    
    if "r2" in profiles and "smoke" in profiles:
        r2_config = profiles["r2"]["config"]
        smoke_config = profiles["smoke"]["config"]
        
        # Порівняти strictness
        r2_coverage = r2_config.get("acceptance", {}).get("coverage_target", 0.0)
        smoke_coverage = smoke_config.get("acceptance", {}).get("coverage_target", 0.0)
        
        if r2_coverage <= smoke_coverage:
            warnings.append("Production (r2) should have stricter coverage_target than smoke")
        
        r2_noop = r2_config.get("preloop", {}).get("max_noop_ratio", 1.0)
        smoke_noop = smoke_config.get("preloop", {}).get("max_noop_ratio", 1.0)
        
        if r2_noop >= smoke_noop:
            warnings.append("Production (r2) should have stricter max_noop_ratio than smoke")
    
    return warnings

def lock_profile(profile_path, validation_result):
    """Створити lock-файл для профілю"""
    lock_path = f"{profile_path}.lock"
    
    lock_data = {
        "profile_path": str(profile_path),
        "checksum": validation_result.checksum,
        "validation": {
            "is_valid": validation_result.is_valid,
            "errors": validation_result.errors,
            "warnings": validation_result.warnings
        },
        "locked_at": str(Path(profile_path).stat().st_mtime),
        "lock_created": "$(date -Iseconds)"
    }
    
    with open(lock_path, 'w') as f:
        json.dump(lock_data, f, indent=2)
    
    print(f"🔒 Profile locked: {lock_path}")
    return lock_path

def check_profile_lock(profile_path):
    """Перевірити чи профіль заблокований та чи не змінювався"""
    lock_path = f"{profile_path}.lock"
    
    if not Path(lock_path).exists():
        return False, "No lock file found"
    
    try:
        with open(lock_path, 'r') as f:
            lock_data = json.load(f)
        
        # Перевірити checksum
        current_config = load_yaml_config(profile_path)
        current_checksum = calculate_config_checksum(current_config)
        
        if current_checksum != lock_data["checksum"]:
            return False, "Profile modified after locking"
        
        return True, "Profile locked and unchanged"
        
    except Exception as e:
        return False, f"Lock validation failed: {e}"

def validate_all_profiles(profiles_dir="configs/profiles"):
    """Валідувати всі профілі в директорії"""
    profiles_path = Path(profiles_dir)
    
    if not profiles_path.exists():
        raise Exception(f"Profiles directory not found: {profiles_dir}")
    
    profiles = {}
    validations = {}
    
    # Знайти всі .yaml файли
    for profile_file in profiles_path.glob("*.yaml"):
        profile_name = profile_file.stem
        
        print(f"📋 Validating profile: {profile_name}")
        
        try:
            config = load_yaml_config(profile_file)
            checksum = calculate_config_checksum(config)
            
            errors, warnings = validate_profile_structure(config, profile_name)
            
            validation = ProfileValidation(
                profile_name=profile_name,
                is_valid=len(errors) == 0,
                errors=errors,
                warnings=warnings,
                checksum=checksum
            )
            
            profiles[profile_name] = {
                "path": profile_file,
                "config": config
            }
            validations[profile_name] = validation
            
            # Вивести результати
            status = "✅ VALID" if validation.is_valid else "❌ INVALID"
            print(f"  Status: {status}")
            print(f"  Checksum: {checksum}")
            
            if errors:
                print(f"  Errors: {len(errors)}")
                for error in errors:
                    print(f"    ❌ {error}")
            
            if warnings:
                print(f"  Warnings: {len(warnings)}")
                for warning in warnings:
                    print(f"    ⚠️ {warning}")
            
        except Exception as e:
            validation = ProfileValidation(
                profile_name=profile_name,
                is_valid=False,
                errors=[str(e)],
                warnings=[],
                checksum=""
            )
            validations[profile_name] = validation
            print(f"  Status: ❌ ERROR - {e}")
    
    # Перевірити консистентність між профілями
    consistency_warnings = validate_profile_consistency(profiles)
    if consistency_warnings:
        print(f"\n⚠️ Consistency warnings:")
        for warning in consistency_warnings:
            print(f"  ⚠️ {warning}")
    
    return validations, profiles

def main():
    parser = argparse.ArgumentParser(description="Validate and lock configuration profiles")
    parser.add_argument("--profiles-dir", default="configs/profiles", 
                       help="Directory containing profile configs")
    parser.add_argument("--lock", action="store_true", 
                       help="Create lock files for valid profiles")
    parser.add_argument("--check-locks", action="store_true",
                       help="Check existing lock files")
    parser.add_argument("--output", default="artifacts/profile_validation.json",
                       help="Output validation report")
    
    args = parser.parse_args()
    
    # Ensure artifacts directory exists
    Path("artifacts").mkdir(exist_ok=True)
    
    print(f"🔧 Configuration Profile Validator")
    print(f"Profiles directory: {args.profiles_dir}")
    
    try:
        if args.check_locks:
            print("\n🔍 Checking existing locks...")
            profiles_path = Path(args.profiles_dir)
            
            for profile_file in profiles_path.glob("*.yaml"):
                is_locked, message = check_profile_lock(profile_file)
                status = "🔒" if is_locked else "🔓"
                print(f"  {profile_file.name}: {status} {message}")
        
        # Validate all profiles
        validations, profiles = validate_all_profiles(args.profiles_dir)
        
        # Create locks if requested
        if args.lock:
            print(f"\n🔒 Creating locks for valid profiles...")
            
            for profile_name, validation in validations.items():
                if validation.is_valid:
                    profile_path = profiles[profile_name]["path"]
                    lock_profile(profile_path, validation)
        
        # Generate report
        report = {
            "validation_summary": {
                "total_profiles": len(validations),
                "valid_profiles": sum(1 for v in validations.values() if v.is_valid),
                "invalid_profiles": sum(1 for v in validations.values() if not v.is_valid)
            },
            "validations": {
                name: {
                    "is_valid": v.is_valid,
                    "errors": v.errors,
                    "warnings": v.warnings,
                    "checksum": v.checksum
                }
                for name, v in validations.items()
            }
        }
        
        with open(args.output, 'w') as f:
            json.dump(report, f, indent=2)
        
        print(f"\n✅ Validation report saved to {args.output}")
        
        # Exit code based on validation results
        all_valid = all(v.is_valid for v in validations.values())
        if all_valid:
            print("🎉 All profiles are valid!")
            return 0
        else:
            print("⚠️ Some profiles have validation errors")
            return 1
            
    except Exception as e:
        print(f"❌ Validation error: {e}")
        return 1

if __name__ == "__main__":
    exit(main())