# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import time
from typing import Callable, Type

from loguru import logger


class CircuitBreakerOpenError(Exception):
    """Raised when the circuit breaker is open."""
    pass


class AsyncCircuitBreaker:
    """
    A simple asyncio-compatible Circuit Breaker.
    """
    def __init__(self, fail_max: int = 5, reset_timeout: int = 60):
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.fail_counter = 0
        self.state = "closed"
        self.last_failure_time = 0.0

    async def call(self, func: Callable, *args, **kwargs):
        """
        Calls the async function, managing circuit state.
        """
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half-open"
            else:
                raise CircuitBreakerOpenError("Circuit is open")

        try:
            result = await func(*args, **kwargs)
            if self.state == "half-open":
                self.state = "closed"
                self.fail_counter = 0
            return result
        except Exception as e:
            self._handle_failure()
            raise e

    def _handle_failure(self):
        self.fail_counter += 1
        self.last_failure_time = time.time()
        if self.fail_counter >= self.fail_max:
            self.state = "open"
            logger.warning(f"Circuit Breaker tripped. Failures: {self.fail_counter}")

    async def __aenter__(self):
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half-open"
            else:
                raise CircuitBreakerOpenError("Circuit is open")
        return self

    async def __aexit__(self, exc_type: Type[BaseException] | None, exc_val: BaseException | None, exc_tb):
        if exc_type:
            # We treat any exception as a failure
            self._handle_failure()
        else:
            if self.state == "half-open":
                self.state = "closed"
                self.fail_counter = 0
        return False  # Propagate exception
