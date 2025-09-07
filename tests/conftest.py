# tests/conftest.py
import os
import sys
import pytest
from tests.fixtures.mock_exchange_factory import MockExchangeFactory

# Ensure project root is on sys.path so 'import core' and 'import tests' work
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), os.pardir))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

# Ignore legacy top-level duplicate tests that cause pytest import-name collisions.
collect_ignore = ["test_composite_sprt.py"]


@pytest.fixture
def mock_exchange_factory():
    """Fixture providing MockExchangeFactory for testing."""
    return MockExchangeFactory()
