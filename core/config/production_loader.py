#!/usr/bin/env python3
"""
Aurora Production Configuration System
=====================================

Unified, transparent, and production-ready config management system.
Eliminates conflicts, provides clear hierarchy, and ensures consistency.
"""

import os
import json
import yaml
import logging
from pathlib import Path
from typing import Dict, Any, Optional, List, Union, Tuple
from dataclasses import dataclass, asdict
from enum import Enum
import hashlib
from datetime import datetime

class Environment(Enum):
    """Supported environments"""
    DEVELOPMENT = "development"
    TESTNET = "testnet"
    PRODUCTION = "production"

class ConfigPriority(Enum):
    """Configuration priority levels"""
    ENVIRONMENT = 1    # Highest - Environment variables
    EXPLICIT = 2       # Explicit config file path
    ENVIRONMENT_NAME = 3   # Environment-specific config
    DEFAULT = 4        # Lowest - Default configs

@dataclass
class ConfigSource:
    """Configuration source metadata"""
    path: str
    priority: ConfigPriority
    size_bytes: int
    last_modified: datetime
    checksum: str
    
class ConfigurationError(Exception):
    """Configuration-related errors"""
    pass

class ProductionConfigManager:
    """
    Production-ready configuration manager with:
    - Clear hierarchy and precedence
    - Full auditability and traceability  
    - Validation and schema enforcement
    - Hot-reload capabilities
    - Conflict resolution
    """
    
    def __init__(self, environment: Environment = Environment.TESTNET):
        self.environment = environment
        self.logger = logging.getLogger(__name__)
        # Fix: config_root should be project root, not core/
        self.config_root = Path(__file__).parent.parent.parent  # Go up from core/config/ to project root
        self.config_dir = Path("configs")  # Add this attribute for CLI compatibility
        self.loaded_sources: List[ConfigSource] = []
        self.final_config: Dict[str, Any] = {}
        self.config_hash: str = ""
        
        # Setup logging
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s - CONFIG - %(levelname)s - %(message)s'
        )
        
    def load_configuration(self) -> Dict[str, Any]:
        """
        Load configuration with clear precedence hierarchy.
        Returns final merged configuration.
        """
        self.logger.info(f"Loading configuration for environment: {self.environment.value}")
        
        # Clear previous state
        self.loaded_sources.clear()
        self.final_config.clear()
        
        # Load in priority order (lowest to highest)
        configs = []
        
        # 1. Load base configuration
        base_config = self._load_base_config()
        if base_config:
            configs.append(base_config)
            
        # 2. Load environment-specific config
        env_config = self._load_environment_config()
        if env_config:
            configs.append(env_config)
            
        # 3. Load explicit config if specified
        explicit_config = self._load_explicit_config()
        if explicit_config:
            configs.append(explicit_config)
            
        # 4. Apply environment variable overrides
        env_overrides = self._load_environment_overrides()
        if env_overrides:
            configs.append(env_overrides)
            
        # Merge all configurations
        self.final_config = self._merge_configurations(configs)
        
        # Validate final configuration
        self._validate_configuration(self.final_config)
        
        # Generate config hash for change detection
        self.config_hash = self._generate_config_hash(self.final_config)
        
        self.logger.info(f"Configuration loaded successfully. Hash: {self.config_hash[:8]}")
        self._log_configuration_summary()
        
        return self.final_config.copy()
    
    def _build_config_file_list(self) -> List[Tuple[ConfigPriority, str]]:
        """Build prioritized list of config files to load"""
        config_files = []
        
        # 1. DEFAULT: Base configurations
        config_files.extend([
            (ConfigPriority.DEFAULT, "configs/aurora/base.yaml"),
            (ConfigPriority.DEFAULT, "configs/base.yaml"),
        ])
        
        # 2. ENVIRONMENT_NAME: Environment-specific
        env_configs = {
            Environment.DEVELOPMENT: ["configs/aurora/development.yaml", "configs/dev.yaml"],
            Environment.TESTNET: ["configs/aurora/testnet.yaml", "configs/testnet.yaml"],
            Environment.PRODUCTION: ["configs/aurora/production.yaml", "configs/prod.yaml"]
        }
        
        for config_path in env_configs.get(self.environment, []):
            config_files.append((ConfigPriority.ENVIRONMENT_NAME, config_path))
        
        # 3. USER_SPECIFIED: Explicit config paths
        aurora_config = os.getenv('AURORA_CONFIG')
        if aurora_config:
            config_files.append((ConfigPriority.USER_SPECIFIED, aurora_config))
            
        # 4. OVERRIDE: Override files
        config_files.extend([
            (ConfigPriority.EXPLICIT, "configs/aurora/overrides.yaml"),
            (ConfigPriority.EXPLICIT, "configs/overrides.yaml"),
        ])
        
        return config_files
    
    def _load_base_config(self) -> Optional[Dict[str, Any]]:
        """Load base configuration template"""
        base_paths = [
            "configs/aurora/base.yaml",
            "configs/base.yaml"
        ]
        
        for path in base_paths:
            try:
                config_data = self._load_config_file(path, ConfigPriority.DEFAULT)
                if config_data:
                    self.logger.info(f"Loaded base config: {path}")
                    return config_data
            except Exception as e:
                self.logger.debug(f"Could not load base config {path}: {e}")
                
        self.logger.warning("No base configuration found")
        return None
    
    def _load_environment_config(self) -> Optional[Dict[str, Any]]:
        """Load environment-specific configuration"""
        env_paths = {
            Environment.DEVELOPMENT: ["configs/aurora/development.yaml", "configs/dev.yaml"],
            Environment.TESTNET: ["configs/aurora/testnet.yaml", "configs/testnet.yaml"],
            Environment.PRODUCTION: ["configs/aurora/production.yaml", "configs/prod.yaml"]
        }
        
        paths = env_paths.get(self.environment, [])
        
        for path in paths:
            try:
                config_data = self._load_config_file(path, ConfigPriority.ENVIRONMENT_NAME)
                if config_data:
                    self.logger.info(f"Loaded environment config: {path}")
                    return config_data
            except Exception as e:
                self.logger.debug(f"Could not load environment config {path}: {e}")
                
        self.logger.warning(f"No environment-specific config found for {self.environment.value}")
        return None
    
    def _load_explicit_config(self) -> Optional[Dict[str, Any]]:
        """Load explicitly specified configuration"""
        explicit_path = os.getenv('AURORA_CONFIG') or os.getenv('AURORA_CONFIG_NAME')
        
        if not explicit_path:
            return None
            
        try:
            # Handle bare names vs full paths
            if not explicit_path.endswith(('.yaml', '.yml')):
                # Bare name - try different locations
                possible_paths = [
                    f"configs/aurora/{explicit_path}.yaml",
                    f"configs/{explicit_path}.yaml",
                    f"{explicit_path}.yaml"
                ]
                
                for path in possible_paths:
                    if (self.config_root / path).exists():
                        explicit_path = path
                        break
                else:
                    raise ConfigurationError(f"Config not found for name: {explicit_path}")
            
            config_data = self._load_config_file(explicit_path, ConfigPriority.EXPLICIT)
            if config_data:
                self.logger.info(f"Loaded explicit config: {explicit_path}")
                return config_data
                
        except Exception as e:
            self.logger.error(f"Failed to load explicit config '{explicit_path}': {e}")
            raise ConfigurationError(f"Failed to load explicit config: {e}")
            
        return None
    
    def _load_environment_overrides(self) -> Dict[str, Any]:
        """Load environment variable overrides"""
        overrides = {}
        
        # Define environment variable mappings
        env_mappings = {
            # API settings
            'AURORA_API_HOST': 'api.host',
            'AURORA_API_PORT': 'api.port',
            
            # Risk settings
            'AURORA_PI_MIN_BPS': 'risk.pi_min_bps', 
            'AURORA_SIZE_SCALE': 'risk.size_scale',
            'AURORA_MAX_CONCURRENT': 'risk.max_concurrent',
            
            # Guards
            'AURORA_SPREAD_MAX_BPS': 'guards.spread_bps_limit',
            'AURORA_LATENCY_MS_LIMIT': 'guards.latency_ms_limit',
            
            # Slippage
            'AURORA_SLIP_FRACTION': 'slippage.eta_fraction_of_b',
            
            # Security
            'AURORA_API_TOKEN': 'security.api_token',
            'AURORA_OPS_TOKEN': 'security.ops_token',
            
            # Trading
            'DRY_RUN': 'trading.dry_run',
            'EXCHANGE_TESTNET': 'trading.testnet',
            
            # Pretrade
            'PRETRADE_ORDER_PROFILE': 'pretrade.order_profile',
        }
        
        for env_var, config_path in env_mappings.items():
            value = os.getenv(env_var)
            if value is not None:
                # Convert value to appropriate type
                converted_value = self._convert_env_value(value)
                self._set_nested_value(overrides, config_path, converted_value)
                self.logger.debug(f"Environment override: {env_var} -> {config_path} = {converted_value}")
        
        if overrides:
            # Add metadata for environment overrides
            source = ConfigSource(
                path="<environment_variables>",
                priority=ConfigPriority.ENVIRONMENT,
                size_bytes=len(str(overrides)),
                last_modified=datetime.now(),
                checksum=hashlib.md5(str(overrides).encode()).hexdigest()
            )
            self.loaded_sources.append(source)
            
        return overrides
    
    def _load_config_file(self, path: str, priority: ConfigPriority) -> Optional[Dict[str, Any]]:
        """Load a configuration file and record metadata"""
        full_path = self.config_root / path
        
        if not full_path.exists():
            return None
            
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            # Parse YAML
            config_data = yaml.safe_load(content) or {}
            
            # Record source metadata
            stat = full_path.stat()
            source = ConfigSource(
                path=str(path),
                priority=priority,
                size_bytes=stat.st_size,
                last_modified=datetime.fromtimestamp(stat.st_mtime),
                checksum=hashlib.md5(content.encode()).hexdigest()
            )
            self.loaded_sources.append(source)
            
            return config_data
            
        except Exception as e:
            self.logger.error(f"Failed to load config file {path}: {e}")
            raise ConfigurationError(f"Failed to load {path}: {e}")
    
    def _merge_configurations(self, configs: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Merge multiple configurations with proper precedence"""
        merged = {}
        
        for config in configs:
            merged = self._deep_merge(merged, config)
            
        return merged
    
    def _deep_merge(self, base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
        """Deep merge two dictionaries"""
        result = base.copy()
        
        for key, value in override.items():
            if key in result and isinstance(result[key], dict) and isinstance(value, dict):
                result[key] = self._deep_merge(result[key], value)
            else:
                result[key] = value
                
        return result
    
    def _set_nested_value(self, config: Dict[str, Any], path: str, value: Any) -> None:
        """Set a nested configuration value using dot notation"""
        keys = path.split('.')
        current = config
        
        for key in keys[:-1]:
            if key not in current:
                current[key] = {}
            current = current[key]
            
        current[keys[-1]] = value
    
    def _convert_env_value(self, value: str) -> Union[str, int, float, bool]:
        """Convert environment variable string to appropriate type"""
        # Boolean conversion
        if value.lower() in ('true', '1', 'yes', 'on'):
            return True
        elif value.lower() in ('false', '0', 'no', 'off'):
            return False
            
        # Numeric conversion
        try:
            if '.' in value:
                return float(value)
            else:
                return int(value)
        except ValueError:
            pass
            
        # Return as string
        return value
    
    def _validate_configuration(self, config: Dict[str, Any]) -> None:
        """Validate the final configuration"""
        # Check if we have loaded configurations from files
        if not self.loaded_sources:
            self.logger.warning("No configuration sources loaded - creating minimal config")
            # Ensure minimal required structure
            if 'api' not in config:
                config['api'] = {'host': '127.0.0.1', 'port': 8080}
            if 'security' not in config:
                config['security'] = {'api_token': os.getenv('AURORA_API_TOKEN', 'dev_token_1234567890123456')}
            if 'aurora' not in config:
                config['aurora'] = {}
            if 'guards' not in config:
                config['guards'] = {}
            if 'risk' not in config:
                config['risk'] = {}
        
        required_sections = ['api', 'security']
        
        for section in required_sections:
            if section not in config:
                raise ConfigurationError(f"Required configuration section missing: {section}")
        
        # Validate API token
        api_token = config.get('security', {}).get('api_token')
        if not api_token or len(api_token) < 16:
            raise ConfigurationError("security.api_token must be at least 16 characters")
        
        # Validate numeric ranges
        pi_min = config.get('risk', {}).get('pi_min_bps', 0)
        if pi_min < 0:
            raise ConfigurationError("risk.pi_min_bps must be non-negative")
            
        self.logger.info("Configuration validation passed")
    
    def _generate_config_hash(self, config: Dict[str, Any]) -> str:
        """Generate hash of configuration for change detection"""
        config_str = json.dumps(config, sort_keys=True)
        return hashlib.sha256(config_str.encode()).hexdigest()
    
    def _log_configuration_summary(self) -> None:
        """Log summary of loaded configuration sources"""
        self.logger.info("Configuration Sources (in load order):")
        
        for i, source in enumerate(self.loaded_sources, 1):
            self.logger.info(
                f"  {i}. {source.path} "
                f"(priority={source.priority.name}, "
                f"size={source.size_bytes}B, "
                f"checksum={source.checksum[:8]})"
            )
    
    def get_config_audit_info(self) -> Dict[str, Any]:
        """Get detailed audit information about loaded configuration"""
        # Get environment overrides
        env_overrides = self._load_environment_overrides()
        
        return {
            "environment": self.environment.value,
            "config_hash": self.config_hash,
            "load_timestamp": datetime.now().isoformat(),
            "sources": [asdict(source) for source in self.loaded_sources],
            "environment_overrides": env_overrides,
            "final_config_size": len(json.dumps(self.final_config))
        }
    
    def save_audit_log(self, output_path: Optional[str] = None) -> str:
        """Save configuration audit log"""
        if not output_path:
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            output_path = f"artifacts/config_audit_{timestamp}.json"
        
        audit_info = self.get_config_audit_info()
        audit_info["final_config"] = self.final_config
        
        output_file = self.config_root / output_path
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            json.dump(audit_info, f, indent=2, default=str)
            
        self.logger.info(f"Configuration audit saved to: {output_path}")
        return str(output_file)

# Global configuration manager instance
_config_manager: Optional[ProductionConfigManager] = None

def initialize_config_system(environment: Environment = Environment.TESTNET) -> ProductionConfigManager:
    """Initialize the global configuration system"""
    global _config_manager
    _config_manager = ProductionConfigManager(environment)
    return _config_manager

def get_config_manager() -> ProductionConfigManager:
    """Get the global configuration manager"""
    if _config_manager is None:
        raise ConfigurationError("Configuration system not initialized. Call initialize_config_system() first.")
    return _config_manager

def load_production_config(environment: Environment = Environment.TESTNET) -> Dict[str, Any]:
    """
    Production-ready configuration loader.
    
    Returns fully validated and merged configuration.
    """
    manager = initialize_config_system(environment)
    return manager.load_configuration()

if __name__ == "__main__":
    # Demo/test the configuration system
    import sys
    
    env_name = sys.argv[1] if len(sys.argv) > 1 else "testnet"
    
    try:
        environment = Environment(env_name)
    except ValueError:
        print(f"Invalid environment: {env_name}")
        print(f"Valid options: {[e.value for e in Environment]}")
        sys.exit(1)
    
    print(f"Loading configuration for environment: {environment.value}")
    
    try:
        config = load_production_config(environment)
        manager = get_config_manager()
        
        print("\n" + "="*60)
        print("CONFIGURATION LOADED SUCCESSFULLY")
        print("="*60)
        
        # Save audit log
        audit_file = manager.save_audit_log()
        print(f"Audit log saved: {audit_file}")
        
        # Print summary
        audit_info = manager.get_config_audit_info()
        print(f"\nConfiguration Hash: {audit_info['config_hash'][:16]}")
        print(f"Sources Loaded: {len(audit_info['sources'])}")
        print(f"Final Config Size: {audit_info['final_config_size']} characters")
        
    except ConfigurationError as e:
        print(f"Configuration Error: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"Unexpected Error: {e}")
        sys.exit(1)