from typing import Any, Dict
from unittest.mock import patch

import pytest

from coreason_adlc_api.db_models import TelemetryLog
from coreason_adlc_api.telemetry.arq_worker import store_telemetry


@pytest.mark.asyncio
async def test_arq_worker_store_telemetry(mock_db_session: Any) -> None:
    """
    Verifies that the store_telemetry job correctly inserts data into the database.
    """
    ctx: Dict[str, Any] = {}
    data = {
        "user_uuid": "00000000-0000-0000-0000-000000000001",
        "auc_id": "test-project",
        "model_name": "gpt-4",
        "request_payload": "hello",
        "response_payload": "world",
        "cost_usd": 0.01,
        "latency_ms": 100,
        "timestamp": "2023-01-01T00:00:00+00:00",
    }

    # Patch the async_session_factory imported in arq_worker
    with patch("coreason_adlc_api.telemetry.arq_worker.async_session_factory") as mock_factory:
        # Configure mock factory to return the mock_db_session context
        mock_factory.return_value.__aenter__.return_value = mock_db_session

        await store_telemetry(ctx, data)

    # Verify session.add was called with a TelemetryLog object
    assert mock_db_session.add.called
    args, _ = mock_db_session.add.call_args
    log_entry = args[0]
    assert isinstance(log_entry, TelemetryLog)
    assert str(log_entry.user_uuid) == data["user_uuid"]
    assert log_entry.auc_id == "test-project"
    assert log_entry.cost_usd == 0.01

    # Verify commit
    assert mock_db_session.commit.called
