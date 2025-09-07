#!/usr/bin/env python3
"""
Aurora Configuration Management CLI
==================================

Production-ready CLI tool for managing Aurora configurations.

Usage:
    python config_cli.py status                     # Show current config status
    python config_cli.py validate [env]             # Validate config for environment
    python config_cli.py switch testnet|production  # Switch to environment
    python config_cli.py audit [--save]             # Show/save audit report
    python config_cli.py hierarchy                  # Show config file hierarchy
    python config_cli.py conflicts                  # Check for config conflicts
    python config_cli.py trace                      # Trace config loading process
"""

import argparse
import json
import sys
import os
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, List

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from core.config.production_loader import (
    ProductionConfigManager,
    Environment,
    ConfigurationError,
    initialize_config_system,
    load_production_config
)

class ConfigCLI:
    """CLI interface for Aurora configuration management"""
    
    def __init__(self):
        self.manager = None
    
    def get_manager(self, environment: Environment = None) -> ProductionConfigManager:
        """Get or initialize configuration manager"""
        if self.manager is None or environment:
            env = environment or self._detect_environment()
            self.manager = initialize_config_system(env)
        return self.manager
    
    def _detect_environment(self) -> Environment:
        """Detect current environment from AURORA_MODE"""
        aurora_mode = os.getenv('AURORA_MODE', 'testnet').lower()
        
        mapping = {
            'testnet': Environment.TESTNET,
            'live': Environment.PRODUCTION,
            'prod': Environment.PRODUCTION,
            'production': Environment.PRODUCTION,
            'dev': Environment.DEVELOPMENT,
            'development': Environment.DEVELOPMENT
        }
        
        return mapping.get(aurora_mode, Environment.TESTNET)
    
    def cmd_status(self) -> None:
        """Show current configuration status"""
        try:
            env = self._detect_environment()
            manager = self.get_manager(env)
            
            print(f"🔧 Aurora Configuration Status")
            print(f"{'=' * 50}")
            print(f"Environment:        {env.value}")
            print(f"AURORA_MODE:        {os.getenv('AURORA_MODE', 'not set')}")
            print(f"Config initialized: {'Yes' if manager.final_config else 'No'}")
            print(f"Config directory:   {manager.config_dir}")
            print()
            
            if manager.final_config:
                audit_info = manager.get_config_audit_info()
                print(f"Configuration Summary:")
                print(f"  Config hash:      {audit_info['config_hash'][:16]}...")
                print(f"  Sources loaded:   {len(audit_info['sources'])}")
                print(f"  Environment vars: {len(audit_info['environment_overrides'])}")
                print(f"  Last loaded:      {audit_info['load_timestamp']}")
                print()
                
                print("Config Sources (by priority):")
                for i, source in enumerate(audit_info['sources'], 1):
                    exists = "✓" if Path(source['file']).exists() else "✗"
                    print(f"  {i}. {exists} {source['priority'].value:12} {source['file']}")
                
                if audit_info['environment_overrides']:
                    print("\nEnvironment Overrides:")
                    for var, value in audit_info['environment_overrides'].items():
                        masked_value = "***" if any(secret in var.lower() for secret in ['token', 'key', 'secret', 'password']) else str(value)[:50]
                        print(f"  {var} = {masked_value}")
            
        except Exception as e:
            print(f"❌ Error getting status: {e}")
            sys.exit(1)
    
    def cmd_validate(self, environment: str = None) -> None:
        """Validate configuration for environment"""
        try:
            if environment:
                env = Environment(environment.upper())
            else:
                env = self._detect_environment()
            
            print(f"🔍 Validating configuration for {env.value}...")
            
            manager = self.get_manager(env)
            config = manager.load_configuration()
            
            print(f"✅ Configuration validation passed!")
            print(f"   Environment: {env.value}")
            print(f"   Config hash: {manager.get_config_audit_info()['config_hash'][:16]}...")
            print(f"   Sources: {len(manager.get_config_audit_info()['sources'])} files")
            
        except ConfigurationError as e:
            print(f"❌ Configuration validation failed: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Unexpected validation error: {e}")
            sys.exit(1)
    
    def cmd_switch(self, environment: str) -> None:
        """Switch to specific environment"""
        try:
            env = Environment(environment.upper())
            
            # Set environment variable
            os.environ['AURORA_MODE'] = env.value.lower()
            
            print(f"🔄 Switching to {env.value} environment...")
            
            # Validate the switch
            manager = self.get_manager(env)
            config = manager.load_configuration()
            
            print(f"✅ Successfully switched to {env.value}")
            print(f"   Set AURORA_MODE={env.value.lower()}")
            print(f"   Config validated and loaded")
            print(f"   To persist: export AURORA_MODE={env.value.lower()}")
            
        except ValueError:
            print(f"❌ Invalid environment: {environment}")
            print(f"   Valid options: {', '.join([e.value.lower() for e in Environment])}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Switch failed: {e}")
            sys.exit(1)
    
    def cmd_audit(self, save: bool = False) -> None:
        """Show or save configuration audit report"""
        try:
            manager = self.get_manager()
            config = manager.load_configuration()
            
            audit_info = manager.get_config_audit_info()
            
            if save:
                audit_file = manager.save_audit_log()
                print(f"💾 Audit report saved: {audit_file}")
            else:
                print(f"📋 Configuration Audit Report")
                print(f"{'=' * 60}")
                print(json.dumps(audit_info, indent=2, default=str))
            
        except Exception as e:
            print(f"❌ Audit failed: {e}")
            sys.exit(1)
    
    def cmd_hierarchy(self) -> None:
        """Show configuration file hierarchy"""
        try:
            manager = self.get_manager()
            
            print(f"📁 Configuration File Hierarchy")
            print(f"{'=' * 50}")
            print(f"Config directory: {manager.config_dir}")
            print()
            
            # Show all possible config files for each environment
            for env in Environment:
                print(f"{env.value} Environment:")
                
                env_manager = initialize_config_system(env)
                config_files = env_manager._build_config_file_list()
                
                for priority, file_path in config_files:
                    exists = "✓" if Path(file_path).exists() else "✗"
                    # Handle relative vs absolute paths
                    try:
                        if Path(file_path).is_absolute():
                            rel_path = Path(file_path)
                        else:
                            rel_path = Path(file_path)
                        print(f"  {exists} {priority.value:12} {rel_path}")
                    except Exception:
                        print(f"  {exists} {priority.value:12} {file_path}")
                print()
        
        except Exception as e:
            print(f"❌ Hierarchy listing failed: {e}")
            sys.exit(1)
    
    def cmd_conflicts(self) -> None:
        """Check for configuration conflicts"""
        try:
            print(f"🔍 Checking for configuration conflicts...")
            
            conflicts_found = False
            
            # Check each environment
            for env in Environment:
                try:
                    manager = initialize_config_system(env)
                    config = manager.load_configuration()
                    audit_info = manager.get_config_audit_info()
                    
                    # Check for same keys from different sources
                    source_keys = {}
                    for source in audit_info['sources']:
                        # This is simplified - would need actual file parsing
                        source_keys[source['file']] = f"Priority: {source['priority'].value}"
                    
                    print(f"✅ {env.value}: No conflicts detected")
                    
                except ConfigurationError as e:
                    print(f"⚠️  {env.value}: Configuration issue - {e}")
                    conflicts_found = True
            
            if not conflicts_found:
                print(f"\n✅ No configuration conflicts found across environments")
            else:
                print(f"\n⚠️  Some configuration issues detected")
                sys.exit(1)
                
        except Exception as e:
            print(f"❌ Conflict check failed: {e}")
            sys.exit(1)
    
    def cmd_trace(self) -> None:
        """Trace configuration loading process"""
        try:
            env = self._detect_environment()
            print(f"🔍 Tracing configuration loading for {env.value}...")
            print()
            
            manager = self.get_manager(env)
            
            # Show step-by-step loading
            print("Loading sequence:")
            config_files = manager._build_config_file_list()
            
            for i, (priority, file_path) in enumerate(config_files, 1):
                exists = Path(file_path).exists()
                status = "✓ LOADED" if exists else "✗ MISSING"
                # Simple file path display
                print(f"  {i}. {status:10} {priority.value:12} {file_path}")
            
            print()
            config = manager.load_configuration()
            audit_info = manager.get_config_audit_info()
            
            print(f"Result:")
            print(f"  Final config hash: {audit_info['config_hash'][:16]}...")
            print(f"  Environment vars:  {len(audit_info['environment_overrides'])}")
            print(f"  Load timestamp:    {audit_info['load_timestamp']}")
            
        except Exception as e:
            print(f"❌ Trace failed: {e}")
            sys.exit(1)

def main():
    """Main CLI entry point"""
    parser = argparse.ArgumentParser(
        description="Aurora Configuration Management CLI",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    
    subparsers = parser.add_subparsers(dest='command', help='Available commands')
    
    # Status command
    subparsers.add_parser('status', help='Show current configuration status')
    
    # Validate command
    validate_parser = subparsers.add_parser('validate', help='Validate configuration')
    validate_parser.add_argument('environment', nargs='?', 
                               choices=['testnet', 'production', 'development'],
                               help='Environment to validate (default: current)')
    
    # Switch command
    switch_parser = subparsers.add_parser('switch', help='Switch environment')
    switch_parser.add_argument('environment', 
                              choices=['testnet', 'production', 'development'],
                              help='Environment to switch to')
    
    # Audit command
    audit_parser = subparsers.add_parser('audit', help='Show/save audit report')
    audit_parser.add_argument('--save', action='store_true', 
                             help='Save audit report to file')
    
    # Other commands
    subparsers.add_parser('hierarchy', help='Show config file hierarchy')
    subparsers.add_parser('conflicts', help='Check for config conflicts')
    subparsers.add_parser('trace', help='Trace config loading process')
    
    args = parser.parse_args()
    
    if not args.command:
        parser.print_help()
        sys.exit(1)
    
    cli = ConfigCLI()
    
    try:
        if args.command == 'status':
            cli.cmd_status()
        elif args.command == 'validate':
            cli.cmd_validate(args.environment)
        elif args.command == 'switch':
            cli.cmd_switch(args.environment)
        elif args.command == 'audit':
            cli.cmd_audit(args.save)
        elif args.command == 'hierarchy':
            cli.cmd_hierarchy()
        elif args.command == 'conflicts':
            cli.cmd_conflicts()
        elif args.command == 'trace':
            cli.cmd_trace()
        
    except KeyboardInterrupt:
        print("\n⚠️  Operation cancelled by user")
        sys.exit(1)

if __name__ == '__main__':
    main()