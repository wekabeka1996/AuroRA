import pytest

pytestmark = [
    pytest.mark.legacy,
    pytest.mark.skip(
        reason="Legacy module archived; superseded by router_v2 & sim subpackage"
    ),
]

from tests.unit.test_enhanced_router_v1 import *
