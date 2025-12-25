from typing import Generator

import pytest

from coreason_adlc_api.middleware.proxy import proxy_breaker


@pytest.fixture(autouse=True)
def reset_circuit_breaker() -> Generator[None, None, None]:
    """Reset circuit breaker state before and after each test."""
    proxy_breaker.state = "closed"
    proxy_breaker.fail_counter = 0
    proxy_breaker.last_failure_time = 0.0
    yield
    proxy_breaker.state = "closed"
    proxy_breaker.fail_counter = 0
    proxy_breaker.last_failure_time = 0.0
