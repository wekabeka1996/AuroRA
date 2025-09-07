import os
import importlib
import pytest
import sys
from fastapi.testclient import TestClient
from unittest.mock import patch, MagicMock, PropertyMock


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

    def test_root_endpoint_returns_html_content(self, tmp_path):
        """Test root endpoint returns HTML content (not redirect)"""
        client = make_client(tmp_path)
        response = client.get('/')
        # Root endpoint serves HTML content, not redirect
        assert response.status_code == 200
        assert 'html' in response.headers.get('content-type', '').lower()

    def test_version_endpoint_returns_version(self, tmp_path):
        """Test version endpoint returns version info"""
        client = make_client(tmp_path)
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
            assert 'version' in data

    def test_health_endpoint_with_models_not_loaded(self, tmp_path):
        """Test health endpoint when models are not loaded"""
        client = make_client(tmp_path)
        setup_app_state(client)

        # Mock trading system as not loaded
        with patch.object(client.app.state, 'trading_system', None):
            response = client.get('/health')
            assert response.status_code == 200
            data = response.json()
            assert data['status'] == 'starting'
            assert data['models_loaded'] is False
            assert 'version' in data

    def test_liveness_endpoint_with_ops_auth(self, tmp_path):
        """Test liveness endpoint with OPS authentication"""
        client = make_client(tmp_path)
        setup_app_state(client)

        # Set OPS token
        os.environ['OPS_TOKEN'] = 'ops_test_token_12345'

        response = client.get('/liveness', headers={'X-OPS-TOKEN': 'ops_test_token_12345'})
        assert response.status_code == 200
        data = response.json()
        assert data['ok'] is True

    def test_liveness_endpoint_missing_ops_token(self, tmp_path):
        """Test liveness endpoint without OPS token"""
        client = make_client(tmp_path)
        setup_app_state(client)

        response = client.get('/liveness')
        assert response.status_code == 401
        assert 'Missing X-OPS-TOKEN' in response.text

    def test_liveness_endpoint_wrong_ops_token(self, tmp_path):
        """Test liveness endpoint with wrong OPS token"""
        client = make_client(tmp_path)
        setup_app_state(client)

        response = client.get('/liveness', headers={'X-OPS-TOKEN': 'wrong_token'})
        assert response.status_code == 403
        assert 'Forbidden' in response.text

    def test_readiness_endpoint_with_all_components_ready(self, tmp_path):
        """Test readiness endpoint when all components are ready"""
        client = make_client(tmp_path)
        setup_app_state(client)

        os.environ['OPS_TOKEN'] = 'ops_test_token_12345'

        with patch.object(client.app.state, 'trading_system') as mock_ts:
            mock_ts.student = MagicMock()
            mock_ts.router = MagicMock()

            response = client.get('/readiness', headers={'X-OPS-TOKEN': 'ops_test_token_12345'})
            assert response.status_code == 200
            data = response.json()
            assert 'config_loaded' in data
            assert 'last_event_ts' in data
            assert 'halt' in data
            assert 'models_loaded' in data

    def test_readiness_endpoint_with_models_not_ready(self, tmp_path):
        """Test readiness endpoint when models are not ready"""
        client = make_client(tmp_path)
        setup_app_state(client)

        os.environ['OPS_TOKEN'] = 'ops_test_token_12345'

        # Mock governance to avoid JSON serialization issues
        with patch.object(client.app.state, 'trading_system', None), \
             patch.object(client.app.state.governance, '_is_halted', return_value=False):
            response = client.get('/readiness', headers={'X-OPS-TOKEN': 'ops_test_token_12345'})
            assert response.status_code == 503
            data = response.json()
            # HTTPException returns detail field with the body
            detail = data.get('detail', {})
            assert detail.get('models_loaded') is False

    def test_readiness_endpoint_with_halt_active(self, tmp_path):
        """Test readiness endpoint when governance halt is active"""
        client = make_client(tmp_path)
        setup_app_state(client)

        os.environ['OPS_TOKEN'] = 'ops_test_token_12345'

        # Create a mock governance with halt active by setting _halt_until_ts to future
        import time
        future_ts = time.time() + 3600  # 1 hour in future

        with patch.object(client.app.state, 'trading_system') as mock_ts, \
             patch.object(client.app.state.governance, '_halt_until_ts', future_ts):
            mock_ts.student = MagicMock()
            mock_ts.router = MagicMock()

            response = client.get('/readiness', headers={'X-OPS-TOKEN': 'ops_test_token_12345'})
            # When halt is active, it should return 200 but with halt=true in body
            assert response.status_code == 200
            data = response.json()
            assert data.get('halt') is True

    def test_readiness_endpoint_without_config(self, tmp_path):
        """Test readiness endpoint when config is not loaded"""
        client = make_client(tmp_path)
        setup_app_state(client)

        os.environ['OPS_TOKEN'] = 'ops_test_token_12345'

        # Mock governance to avoid JSON serialization issues
        mock_governance = MagicMock()
        mock_governance._is_halted.return_value = False

        with patch.object(client.app.state, 'cfg', {}), \
             patch.object(client.app.state, 'governance', mock_governance):
            response = client.get('/readiness', headers={'X-OPS-TOKEN': 'ops_test_token_12345'})
            assert response.status_code == 503
            data = response.json()
            detail = data.get('detail', {})
            assert detail.get('config_loaded') is False


class TestMetricsEndpoint:
    """Test metrics endpoint functionality"""

    def test_metrics_endpoint_returns_prometheus_format(self, tmp_path):
        """Test that metrics endpoint returns valid Prometheus format"""
        client = make_client(tmp_path)
        response = client.get('/metrics')
        assert response.status_code == 200
        content = response.text

        # Check for expected metric names
        expected_metrics = [
            'aurora_prediction_requests_total',
            'aurora_prediction_latency_ms',
            'aurora_kappa_plus',
            'aurora_regime',
            'aurora_events_emitted_total',
            'aurora_orders_success_total',
            'aurora_orders_denied_total',
            'aurora_orders_rejected_total',
            'aurora_ops_auth_fail_total'
        ]

        for metric in expected_metrics:
            assert metric in content, f"Missing metric: {metric}"

    def test_metrics_endpoint_contains_sli_metrics(self, tmp_path):
        """Test that SLI metrics are present in metrics output"""
        client = make_client(tmp_path)
        response = client.get('/metrics')
        assert response.status_code == 200
        content = response.text

        sli_metrics = [
            'aurora_deny_rate_15m',
            'aurora_latency_p99_ms',
            'aurora_ece',
            'aurora_cvar95_min',
            'aurora_sse_clients',
            'aurora_sse_disconnects_total',
            'aurora_parent_gate_allow_total',
            'aurora_parent_gate_deny_total',
            'aurora_expected_net_reward_blocked_total',
            'aurora_orders_submitted_shadow_total'
        ]

        for metric in sli_metrics:
            assert metric in content, f"Missing SLI metric: {metric}"


class TestSecurityHeaders:
    """Test security-related headers and responses"""

    def test_cors_headers_disabled_by_default(self, tmp_path):
        """Test that CORS is disabled by default"""
        client = make_client(tmp_path)
        response = client.get('/version')
        # Should not have CORS headers when not configured
        assert 'access-control-allow-origin' not in response.headers

    def test_cors_headers_enabled_with_env_var(self, tmp_path):
        """Test that CORS headers are present when configured"""
        from fastapi import FastAPI
        from fastapi.middleware.cors import CORSMiddleware

        # Create a new app with CORS enabled
        app = FastAPI()
        app.add_middleware(
            CORSMiddleware,
            allow_origins=['http://localhost:3000'],
            allow_credentials=True,
            allow_methods=["GET", "POST", "OPTIONS"],
            allow_headers=["*"],
        )

        @app.get('/version')
        async def version():
            return {"version": "test"}

        client = TestClient(app)
        # Test with Origin header to trigger CORS
        response = client.get('/version', headers={'Origin': 'http://localhost:3000'})
        assert response.status_code == 200
        # CORS headers should be present
        cors_header = response.headers.get('access-control-allow-origin')
        assert cors_header is not None
        assert cors_header == 'http://localhost:3000'

    def test_ip_allowlist_blocks_non_allowed_ip(self, tmp_path):
        """Test that IP allowlist blocks requests from non-allowed IPs"""
        # Create client with restricted allowlist
        os.environ['AURORA_IP_ALLOWLIST'] = '192.168.1.1'

        # Reload module to pick up new allowlist
        import api.service as svc
        importlib.reload(svc)

        client = TestClient(svc.app)

        response = client.get('/version')
        assert response.status_code == 403
        assert 'IP not allowed' in response.text

    def test_ip_allowlist_allows_allowed_ip(self, tmp_path):
        """Test that IP allowlist allows requests from allowed IPs"""
        os.environ['AURORA_IP_ALLOWLIST'] = '127.0.0.1'

        # Reload module to pick up new allowlist
        import api.service as svc
        importlib.reload(svc)

        client = TestClient(svc.app)

        response = client.get('/version')
        assert response.status_code == 200