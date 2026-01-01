import time
from collections import deque
from typing import Any, Dict, Type


class CoreasonError(Exception):
    pass


class CircuitOpenError(CoreasonError):
    pass


class QuotaExceededError(Exception):
    pass


class QuotaGuard:
    def __init__(self, redis_client: Any, limit: float) -> None:
        self.redis_client = redis_client
        self.limit = limit

    async def check_and_increment(self, user_id: str, cost: float) -> None:
        pass

    async def check_status(self, user_id: str) -> Dict[str, Any]:
        return {"current_usage": 0.0, "limit": self.limit, "remaining": self.limit}


class AsyncCircuitBreaker:
    def __init__(self, fail_max: int = 5, reset_timeout: float = 60) -> None:
        self.fail_max = fail_max
        self.reset_timeout = reset_timeout
        self.state = "closed"
        self.failure_history: deque[float] = deque()
        self.last_failure_time = 0.0

    async def __aenter__(self) -> "AsyncCircuitBreaker":
        if self.state == "open":
            if time.time() - self.last_failure_time > self.reset_timeout:
                self.state = "half-open"
            else:
                raise CircuitOpenError("Circuit is open")
        return self

    async def __aexit__(self, exc_type: Type[BaseException] | None, exc_val: BaseException | None, exc_tb: Any) -> bool:
        if exc_type:
            if exc_type is not CircuitOpenError:
                self.state = "open"
                self.last_failure_time = time.time()
        return False


class DeterminismInterceptor:
    @staticmethod
    def enforce_config(config: Dict[str, Any]) -> Dict[str, Any]:
        config["temperature"] = 0.0
        return config


def scrub_pii_payload(payload: Any) -> Any:
    return payload


class IERLogger:
    def log_llm_transaction(self, **kwargs: Any) -> None:
        pass
