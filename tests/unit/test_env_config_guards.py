"""
Unit tests for core/env_config.py live-only guards and configuration loading.

Tests the R1.5b requirement: .env must contain ONLY live keys/endpoints;
if testnet variables are present, runner startup should fail with clear message.
"""

import os
import pytest
from unittest.mock import patch, mock_open
from core.env_config import BinanceCfg, load_binance_cfg


class TestBinanceCfg:
    """Test BinanceCfg dataclass validation."""
    
    def test_binance_cfg_creation_valid(self):
        """Test valid BinanceCfg creation."""
        cfg = BinanceCfg(
            env="live",
            api_key="valid_key",
            api_secret="valid_secret",
            base_url="https://api.binance.com",
            ws_url="wss://stream.binance.com:9443"
        )
        
        assert cfg.env == "live"
        assert cfg.api_key == "valid_key"
        assert cfg.api_secret == "valid_secret"
        assert cfg.base_url == "https://api.binance.com"
        assert cfg.ws_url == "wss://stream.binance.com:9443"
    
    def test_binance_cfg_minimal(self):
        """Test BinanceCfg with minimal required fields."""
        cfg = BinanceCfg(
            env="live",
            api_key="key",
            api_secret="secret",
            base_url="https://api.binance.com",
            ws_url="wss://stream.binance.com:9443"
        )
        
        assert cfg.env == "live"
        assert cfg.api_key == "key"
        assert cfg.api_secret == "secret"


class TestLoadBinanceCfg:
    """Test load_binance_cfg() guards and validation."""
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key',
        'BINANCE_API_SECRET_LIVE': 'live_secret',
        'BINANCE_USDM_BASE_URL': 'https://api.binance.com',
        'BINANCE_USDM_WS_URL': 'wss://stream.binance.com:9443/stream'
    }, clear=True)
    def test_load_binance_cfg_valid_live(self, mock_load_dotenv):
        """Test successful loading of valid live configuration."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        # Ensure no testnet variables are present
        all_binance_vars = [
            'BINANCE_API_KEY_TESTNET', 'BINANCE_API_SECRET_TESTNET',
            'BINANCE_USDM_BASE_URL_TESTNET', 'BINANCE_USDM_WS_URL_TESTNET'
        ]
        for var in all_binance_vars:
            if var in os.environ:
                del os.environ[var]
        
        cfg = load_binance_cfg()
        
        assert cfg.env == "live"
        assert cfg.api_key == "live_key"
        assert cfg.api_secret == "live_secret"
        assert cfg.base_url == "https://api.binance.com"
        assert cfg.ws_url == "wss://stream.binance.com:9443/stream"
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'testnet'
    }, clear=True)
    def test_load_binance_cfg_testnet_missing_credentials(self, mock_load_dotenv):
        """Test that testnet BINANCE_ENV requires testnet credentials."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        # Ensure no testnet variables are present
        testnet_vars = [
            'BINANCE_API_KEY_TESTNET', 'BINANCE_API_SECRET_TESTNET',
            'BINANCE_USDM_BASE_URL_TESTNET', 'BINANCE_USDM_WS_URL_TESTNET'
        ]
        for var in testnet_vars:
            if var in os.environ:
                del os.environ[var]
        
        with pytest.raises(RuntimeError, match="Missing testnet credentials"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock the actual import
    @patch.dict(os.environ, {}, clear=True)
    def test_load_binance_cfg_missing_env(self, mock_load_dotenv):
        """Test that missing BINANCE_ENV defaults to live and validates."""
        # Should fail due to missing API credentials
        mock_load_dotenv.return_value = None  # Ensure no .env loading
        with pytest.raises(RuntimeError, match="Missing live credentials"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key',
        'BINANCE_API_SECRET_LIVE': 'live_secret',
        'BINANCE_API_KEY_TESTNET': 'testnet_key'
    }, clear=True)
    def test_load_binance_cfg_detects_testnet_key(self, mock_load_dotenv):
        """Test that presence of testnet keys is detected and rejected."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        with pytest.raises(RuntimeError, match="Both live and testnet credential variables present"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key',
        'BINANCE_API_SECRET_LIVE': 'live_secret',
        'BINANCE_API_SECRET_TESTNET': 'testnet_secret'
    }, clear=True)
    def test_load_binance_cfg_detects_testnet_secret(self, mock_load_dotenv):
        """Test that presence of testnet secret is detected and rejected."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        with pytest.raises(RuntimeError, match="Both live and testnet credential variables present"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock the actual import
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key'
    }, clear=True)
    def test_load_binance_cfg_missing_secret(self, mock_load_dotenv):
        """Test that missing API secret is detected."""
        mock_load_dotenv.return_value = None  # Ensure no .env loading
        with pytest.raises(RuntimeError, match="Missing live credentials"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': '',
        'BINANCE_API_SECRET_LIVE': 'secret'
    }, clear=True)
    def test_load_binance_cfg_empty_key(self, mock_load_dotenv):
        """Test that empty API key is detected."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        # Ensure no testnet variables are present
        testnet_vars = [
            'BINANCE_API_KEY_TESTNET', 'BINANCE_API_SECRET_TESTNET',
            'BINANCE_USDM_BASE_URL_TESTNET', 'BINANCE_USDM_WS_URL_TESTNET'
        ]
        for var in testnet_vars:
            if var in os.environ:
                del os.environ[var]
        
        with pytest.raises(RuntimeError, match="Missing live credentials"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'key',
        'BINANCE_API_SECRET_LIVE': ''
    }, clear=True)
    def test_load_binance_cfg_empty_secret(self, mock_load_dotenv):
        """Test that empty API secret is detected."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        # Ensure no testnet variables are present
        testnet_vars = [
            'BINANCE_API_KEY_TESTNET', 'BINANCE_API_SECRET_TESTNET',
            'BINANCE_USDM_BASE_URL_TESTNET', 'BINANCE_USDM_WS_URL_TESTNET'
        ]
        for var in testnet_vars:
            if var in os.environ:
                del os.environ[var]
        
        with pytest.raises(RuntimeError, match="Missing live credentials"):
            load_binance_cfg()
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key',
        'BINANCE_API_SECRET_LIVE': 'live_secret'
    }, clear=True)
    def test_load_binance_cfg_default_urls(self, mock_load_dotenv):
        """Test that default URLs are used when not specified."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        # Ensure no testnet variables are present
        testnet_vars = [
            'BINANCE_API_KEY_TESTNET', 'BINANCE_API_SECRET_TESTNET',
            'BINANCE_USDM_BASE_URL_TESTNET', 'BINANCE_USDM_WS_URL_TESTNET'
        ]
        for var in testnet_vars:
            if var in os.environ:
                del os.environ[var]
        
        cfg = load_binance_cfg()
        
        assert cfg.base_url == "https://fapi.binance.com"
        assert cfg.ws_url == "wss://fstream.binance.com/stream"
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key',
        'BINANCE_API_SECRET_LIVE': 'live_secret',
        'BINANCE_USDM_BASE_URL': 'https://custom.binance.com',
        'BINANCE_USDM_WS_URL': 'wss://custom.stream.binance.com:9443/stream'
    }, clear=True)
    def test_load_binance_cfg_custom_urls(self, mock_load_dotenv):
        """Test that custom URLs are used when specified."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        # Ensure no testnet variables are present
        testnet_vars = [
            'BINANCE_API_KEY_TESTNET', 'BINANCE_API_SECRET_TESTNET',
            'BINANCE_USDM_BASE_URL_TESTNET', 'BINANCE_USDM_WS_URL_TESTNET'
        ]
        for var in testnet_vars:
            if var in os.environ:
                del os.environ[var]
        
        cfg = load_binance_cfg()
        
        assert cfg.base_url == "https://custom.binance.com"
        assert cfg.ws_url == "wss://custom.stream.binance.com:9443/stream"
    
    @patch('core.env_config.load_dotenv')  # Mock dotenv loading
    @patch.dict(os.environ, {
        'BINANCE_ENV': 'live',
        'BINANCE_API_KEY_LIVE': 'live_key',
        'BINANCE_API_SECRET_LIVE': 'live_secret',
        'BINANCE_API_KEY_TESTNET': 'testnet_key',
        'BINANCE_API_SECRET_TESTNET': 'testnet_secret'
    }, clear=True)
    def test_load_binance_cfg_both_keys_rejected(self, mock_load_dotenv):
        """Test that presence of both live and testnet keys is rejected."""
        # Prevent dotenv from loading any external .env file
        mock_load_dotenv.return_value = None
        
        with pytest.raises(RuntimeError, match="Both live and testnet credential variables present"):
            load_binance_cfg()


class TestEnvFileLoading:
    """Test .env file loading behavior."""
    
    @patch('builtins.open', new_callable=mock_open, read_data='''
BINANCE_ENV=live
BINANCE_API_KEY_LIVE=file_key
BINANCE_API_SECRET_LIVE=file_secret
''')
    @patch('os.path.exists', return_value=True)
    @patch.dict(os.environ, {}, clear=True)
    def test_load_from_env_file(self, mock_exists, mock_file):
        """Test loading configuration from .env file."""
        with patch('dotenv.load_dotenv') as mock_load_dotenv:
            # Simulate dotenv loading
            mock_load_dotenv.side_effect = lambda: os.environ.update({
                'BINANCE_ENV': 'live',
                'BINANCE_API_KEY_LIVE': 'file_key',
                'BINANCE_API_SECRET_LIVE': 'file_secret'
            })
            
            cfg = load_binance_cfg()
            
            assert cfg.env == "live"
            assert cfg.api_key == "file_key"
            assert cfg.api_secret == "file_secret"
    
    @patch('builtins.open', new_callable=mock_open, read_data='''
BINANCE_ENV=live
BINANCE_API_KEY_LIVE=live_key
BINANCE_API_SECRET_LIVE=live_secret
BINANCE_API_KEY_TESTNET=testnet_key
''')
    @patch('os.path.exists', return_value=True)
    @patch.dict(os.environ, {}, clear=True)
    def test_env_file_with_testnet_rejected(self, mock_exists, mock_file):
        """Test that .env file with testnet keys is rejected."""
        with patch('dotenv.load_dotenv') as mock_load_dotenv:
            mock_load_dotenv.side_effect = lambda: os.environ.update({
                'BINANCE_ENV': 'live',
                'BINANCE_API_KEY_LIVE': 'live_key',
                'BINANCE_API_SECRET_LIVE': 'live_secret',
                'BINANCE_API_KEY_TESTNET': 'testnet_key'
            })
            
            with pytest.raises(RuntimeError, match="Both live and testnet credential variables present"):
                load_binance_cfg()