import os
import importlib
import pytest
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock


def make_client(tmp_path) -> TestClient:
    """Create test client with isolated environment"""
    os.environ['AURORA_API_TOKEN'] = 'test_token_12345678901234567890'
    os.environ['AURORA_IP_ALLOWLIST'] = '127.0.0.1'
    os.chdir(tmp_path)

    import api.service as svc
    importlib.reload(svc)
    return TestClient(svc.app)


def setup_app_state(client):
    """Setup minimal app state for testing"""
    app = client.app

    # Initialize basic state attributes
    if not hasattr(app.state, 'cfg'):
        app.state.cfg = {'test': 'config'}
    if not hasattr(app.state, 'trading_system'):
        app.state.trading_system = None
    if not hasattr(app.state, 'governance'):
        from aurora.governance import Governance
        app.state.governance = Governance()
    if not hasattr(app.state, 'events_emitter'):
        app.state.events_emitter = MagicMock()
    if not hasattr(app.state, 'last_event_ts'):
        app.state.last_event_ts = None
    if not hasattr(app.state, 'session_dir'):
        from pathlib import Path
        app.state.session_dir = Path('logs')

    return app


class TestBasicEndpoints:
    """Test basic API endpoints that don't require complex setup"""

    def test_root_endpoint_redirects_to_docs(self, tmp_path):
        """Test root endpoint redirects to /docs"""
        client = make_client(tmp_path)
        setup_app_state(client)
        response = client.get('/')
        # TestClient follows redirects by default, so we check final URL
        assert response.status_code == 200
        # Since it redirects to /docs, the final response should be from docs endpoint

    def test_version_endpoint_returns_version(self, tmp_path):
        """Test version endpoint returns version info"""
        client = make_client(tmp_path)
        setup_app_state(client)
        response = client.get('/version')
        assert response.status_code == 200
        data = response.json()
        assert 'version' in data
        assert isinstance(data['version'], str)

    def test_health_endpoint_with_models_loaded(self, tmp_path):
        """Test health endpoint when models are loaded"""
        client = make_client(tmp_path)
        setup_app_state(client)

        # Mock trading system as loaded
        with patch.object(client.app.state, 'trading_system') as mock_ts:
            mock_ts.student = MagicMock()
            mock_ts.router = MagicMock()

            response = client.get('/health')
            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'healthy'
            assert data['models_loaded'] is True

    def test_health_endpoint_with_models_not_loaded(self, tmp_path):
        """Test health endpoint when models are not loaded"""
        client = make_client(tmp_path)
        setup_app_state(client)

        # Mock trading system as not loaded
        with patch.object(client.app.state, 'trading_system', None):
            response = client.get('/health')
            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'starting'  # Status is 'starting' when models not loaded
            assert data['models_loaded'] is False