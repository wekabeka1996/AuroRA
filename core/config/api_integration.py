"""
Aurora API Service Integration Layer
===================================

Replaces the legacy config loading system in api/service.py with 
the new production-ready configuration manager.
"""

import os
import sys
import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

# Import the new production config system
from core.config.production_loader import (
    ProductionConfigManager, 
    Environment, 
    ConfigurationError,
    load_production_config,
    initialize_config_system,
    get_config_manager
)

# Import existing Aurora components
from core.aurora_event_logger import AuroraEventLogger
from core.env_config import get_runtime_mode, validate_aurora_mode

def determine_environment() -> Environment:
    """Determine the Aurora environment from runtime settings"""
    
    aurora_mode = os.getenv('AURORA_MODE', 'testnet').lower().strip()
    
    # Map Aurora modes to standard environments
    mode_mapping = {
        'testnet': Environment.TESTNET,
        'live': Environment.PRODUCTION,
        'prod': Environment.PRODUCTION,
        'production': Environment.PRODUCTION,
        'dev': Environment.DEVELOPMENT,
        'development': Environment.DEVELOPMENT
    }
    
    environment = mode_mapping.get(aurora_mode, Environment.TESTNET)
    
    logging.info(f"Aurora mode '{aurora_mode}' mapped to environment: {environment.value}")
    return environment

def validate_production_config(config: dict) -> None:
    """Additional Aurora-specific validation"""
    
    # Validate Aurora-specific requirements
    if not config.get('security', {}).get('api_token'):
        raise ConfigurationError("Aurora API token (AURORA_API_TOKEN) is required")
    
    # Validate environment consistency
    aurora_mode = os.getenv('AURORA_MODE', 'testnet')
    config_env = config.get('env', 'unknown')
    
    if aurora_mode == 'testnet' and config_env not in ['testnet', 'development']:
        logging.warning(f"Environment mismatch: AURORA_MODE={aurora_mode} but config env={config_env}")
    
    logging.info("Aurora production config validation passed")

@asynccontextmanager
async def production_lifespan(app):
    """
    Production-ready lifespan manager for Aurora API.
    
    Replaces the legacy config loading in api/service.py with
    the new transparent configuration system.
    """
    
    logger = logging.getLogger("aurora.config")
    
    try:
        # 1. Determine environment
        environment = determine_environment()
        logger.info(f"Starting Aurora API in {environment.value} environment")
        
        # 2. Initialize configuration system
        config_manager = initialize_config_system(environment)
        
        # 3. Load configuration
        config = config_manager.load_configuration()
        
        # 4. Additional Aurora validation
        validate_production_config(config)
        
        # 5. Store in app state
        app.state.config = config
        app.state.config_manager = config_manager
        app.state.environment = environment
        
        # 6. Save audit log
        audit_file = config_manager.save_audit_log()
        logger.info(f"Configuration audit saved: {audit_file}")
        
        # 7. Emit configuration event (for observability)
        try:
            events_emitter = getattr(app.state, 'events_emitter', None)
            if events_emitter:
                audit_info = config_manager.get_config_audit_info()
                events_emitter.emit('CONFIG.LOADED', {
                    'environment': environment.value,
                    'config_hash': audit_info['config_hash'][:16],
                    'sources_count': len(audit_info['sources']),
                    'audit_file': audit_file
                })
        except Exception as e:
            logger.warning(f"Could not emit config event: {e}")
        
        # 8. Validate Aurora mode consistency
        try:
            validate_aurora_mode()
            runtime_mode = get_runtime_mode()
            logger.info(f"Aurora runtime mode validated: {runtime_mode}")
        except Exception as e:
            logger.error(f"Aurora mode validation failed: {e}")
            raise
        
        logger.info("Aurora API startup completed successfully")
        
        # Yield control to the application
        yield
        
    except ConfigurationError as e:
        logger.error(f"Configuration error during startup: {e}")
        raise
    except Exception as e:
        logger.error(f"Unexpected error during startup: {e}")
        raise
    finally:
        # Cleanup
        logger.info("Aurora API shutdown completed")

def get_current_config() -> dict:
    """Get the current loaded configuration"""
    try:
        manager = get_config_manager()
        return manager.final_config.copy()
    except ConfigurationError:
        # Fallback for when the new system isn't initialized
        return {}

def get_config_audit_summary() -> dict:
    """Get configuration audit summary"""
    try:
        manager = get_config_manager()
        return manager.get_config_audit_info()
    except ConfigurationError:
        return {"error": "Configuration system not initialized"}

# Legacy compatibility functions
def load_config_precedence() -> dict:
    """
    Legacy compatibility function.
    
    This replaces the old load_config_precedence() from common/config.py
    with the new production system.
    """
    
    # Determine environment
    environment = determine_environment()
    
    # Load with new system
    try:
        config = load_production_config(environment)
        return config
    except Exception as e:
        logging.error(f"Failed to load config with new system: {e}")
        # Return empty dict as fallback
        return {}

# Export for backward compatibility
__all__ = [
    'production_lifespan',
    'determine_environment', 
    'validate_production_config',
    'get_current_config',
    'get_config_audit_summary',
    'load_config_precedence'  # Legacy compatibility
]