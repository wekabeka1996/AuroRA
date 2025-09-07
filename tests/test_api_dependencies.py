# -*- coding: utf-8 -*-
"""
Tests for API dependencies and FastAPI service functionality.
"""
import pytest
import requests
import time
import subprocess
import json
from pathlib import Path
import sys
import os

# Add project root to sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


class TestApiDependencies:
    """Test import and basic functionality of API dependencies."""
    
    def test_fastapi_import(self):
        """Test that FastAPI can be imported."""
        try:
            import fastapi
            assert hasattr(fastapi, 'FastAPI')
            assert hasattr(fastapi, 'HTTPException')
        except ImportError:
            pytest.fail("FastAPI not installed or not importable")
    
    def test_uvicorn_import(self):
        """Test that uvicorn can be imported."""
        try:
            import uvicorn
            assert hasattr(uvicorn, 'run')
        except ImportError:
            pytest.fail("uvicorn not installed or not importable")
    
    def test_pydantic_import(self):
        """Test that pydantic can be imported."""
        try:
            import pydantic
            assert hasattr(pydantic, 'BaseModel')
        except ImportError:
            pytest.fail("pydantic not installed or not importable")
    
    def test_prometheus_client_import(self):
        """Test that prometheus_client can be imported."""
        try:
            import prometheus_client
            assert hasattr(prometheus_client, 'make_asgi_app')
            assert hasattr(prometheus_client, 'Histogram')
            assert hasattr(prometheus_client, 'Gauge')
            assert hasattr(prometheus_client, 'Counter')
        except ImportError:
            pytest.fail("prometheus_client not installed or not importable")
    
    def test_dotenv_import(self):
        """Test that python-dotenv can be imported."""
        try:
            import dotenv
            assert hasattr(dotenv, 'load_dotenv')
            assert hasattr(dotenv, 'find_dotenv')
        except ImportError:
            pytest.fail("python-dotenv not installed or not importable")
    
    def test_api_service_import(self):
        """Test that the API service can be imported without errors."""
        try:
            from api.service import app
            assert app is not None
            assert hasattr(app, 'get')
            assert hasattr(app, 'post')
        except ImportError as e:
            pytest.fail(f"API service not importable: {e}")


class TestApiModels:
    """Test API model functionality."""
    
    def test_pydantic_models(self):
        """Test that pydantic models work correctly."""
        from pydantic import BaseModel
        
        class TestModel(BaseModel):
            name: str
            value: int
        
        # Test valid data
        model = TestModel(name="test", value=42)
        assert model.name == "test"
        assert model.value == 42
        
        # Test validation
        with pytest.raises(Exception):  # pydantic validation error
            TestModel(name="test", value="not_a_number")
    
    def test_fastapi_response_models(self):
        """Test FastAPI response model creation."""
        from fastapi.responses import JSONResponse
        
        response = JSONResponse(content={"status": "ok", "data": {"test": "value"}})
        assert response.status_code == 200


class TestPrometheusMetrics:
    """Test Prometheus metrics functionality."""
    
    def test_prometheus_metrics_creation(self):
        """Test creating Prometheus metrics."""
        from prometheus_client import Histogram, Gauge, Counter

        # Test histogram
        histogram = Histogram('test_histogram_deps', 'Test histogram metric')
        histogram.observe(1.5)

        # Test gauge
        gauge = Gauge('test_gauge_deps', 'Test gauge metric')
        gauge.set(42)

        # Test counter
        counter = Counter('test_counter_deps', 'Test counter metric')
        counter.inc()
        counter.inc(5)

        # Verify metrics exist (use _value attribute of samples for histograms)
        assert len(list(histogram.collect()[0].samples)) > 0
        assert gauge._value._value == 42
        assert counter._value._value == 6

    def test_prometheus_asgi_app(self):
        """Test creating Prometheus ASGI app."""
        from prometheus_client import make_asgi_app
        
        metrics_app = make_asgi_app()
        assert metrics_app is not None


class TestEnvironmentConfig:
    """Test environment configuration loading."""
    
    def test_dotenv_loading(self):
        """Test loading environment variables from .env file."""
        from dotenv import load_dotenv
        import tempfile
        
        # Create temporary .env file
        with tempfile.NamedTemporaryFile(mode='w', suffix='.env', delete=False) as f:
            f.write("TEST_VAR=test_value\n")
            f.write("TEST_NUM=42\n")
            temp_env_file = f.name
        
        try:
            # Load the temporary .env file
            load_dotenv(temp_env_file)
            
            # Check if variables are loaded
            assert os.getenv("TEST_VAR") == "test_value"
            assert os.getenv("TEST_NUM") == "42"
        finally:
            # Clean up
            os.unlink(temp_env_file)
            # Remove from environment
            if "TEST_VAR" in os.environ:
                del os.environ["TEST_VAR"]
            if "TEST_NUM" in os.environ:
                del os.environ["TEST_NUM"]


class TestApiServiceStartup:
    """Test API service startup and basic endpoints."""
    
    def test_api_app_creation(self):
        """Test that the FastAPI app is created correctly."""
        from api.service import app
        
        # Check app properties
        assert app.title == "AURORA Trading API"
        assert hasattr(app, 'router')
        assert hasattr(app, 'routes')
    
    def test_health_endpoint_exists(self):
        """Test that health endpoint exists in the app."""
        from api.service import app
        
        # Check if health endpoint is registered
        routes = [route.path for route in app.routes]
        assert "/health" in routes or any("/health" in route for route in routes)
    
    def test_trading_system_integration(self):
        """Test that TradingSystem integration works."""
        from api.service import app
        
        # Test that we can access app state (will be None initially)
        # Trading system is loaded during lifespan, not at import
        assert hasattr(app, 'state')
        assert app is not None


class TestCoreModules:
    """Test core module imports that API depends on."""
    
    def test_core_aurora_imports(self):
        """Test that core Aurora modules can be imported."""
        try:
            from core.aurora.pretrade import gate_latency, gate_slippage, gate_expected_return, gate_trap
            assert callable(gate_latency)
            assert callable(gate_slippage)
            assert callable(gate_expected_return)
            assert callable(gate_trap)
        except ImportError as e:
            pytest.fail(f"Core Aurora modules not importable: {e}")
    
    def test_env_config_import(self):
        """Test that env_config module can be imported."""
        try:
            from core.env_config import load_binance_cfg
            assert callable(load_binance_cfg)
        except ImportError as e:
            pytest.fail(f"env_config module not importable: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])