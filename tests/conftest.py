"""
Pytest configuration and fixtures
"""

import sys
from pathlib import Path

import pytest

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))


@pytest.fixture
def mock_request():
    """Create a mock HTTP request object"""

    class MockRequest:
        def __init__(self):
            self.headers = {}
            self.remote_addr = "192.168.1.100"
            self.META = {}
            self.method = "GET"
            self.path = "/api/test"

    return MockRequest()


@pytest.fixture
def sample_violation():
    """Create a sample violation for testing"""
    from datetime import datetime

    from ratethrottle.core import RateThrottleViolation

    return RateThrottleViolation(
        identifier="192.168.1.100",
        rule_name="test_rule",
        timestamp=datetime.now().isoformat(),
        requests_made=101,
        limit=100,
        blocked_until=None,
        retry_after=60,
        scope="ip",
        metadata={},
    )


# Markers for different test categories
def pytest_configure(config):
    """Configure custom pytest markers"""
    config.addinivalue_line("markers", "redis: mark test as requiring Redis connection")
    config.addinivalue_line("markers", "slow: mark test as slow running")
    config.addinivalue_line("markers", "integration: mark test as integration test")
