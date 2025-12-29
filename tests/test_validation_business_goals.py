# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import json
import uuid
from datetime import datetime, timezone
from typing import Generator
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from coreason_adlc_api.config import settings
from coreason_adlc_api.middleware.budget import check_budget_guardrail
from coreason_adlc_api.middleware.telemetry import async_log_telemetry
from coreason_adlc_api.workbench.locking import acquire_draft_lock
from coreason_adlc_api.workbench.schemas import AccessMode

try:
    import presidio_analyzer  # noqa: F401

    HAS_PRESIDIO = True
except ImportError:
    HAS_PRESIDIO = False


@pytest.fixture
def mock_redis() -> Generator[MagicMock, None, None]:
    with patch("coreason_adlc_api.middleware.budget.get_redis_client") as m:
        client = MagicMock()
        m.return_value = client
        yield client


@pytest.fixture
def mock_redis_telemetry() -> Generator[MagicMock, None, None]:
    with patch("coreason_adlc_api.middleware.telemetry.get_redis_client") as m:
        client = MagicMock()
        m.return_value = client
        yield client


@pytest.fixture
def mock_db_pool() -> Generator[MagicMock, None, None]:
    with patch("coreason_adlc_api.workbench.locking.get_pool") as m:
        pool = MagicMock()
        m.return_value = pool

        # Setup connection mock
        conn = AsyncMock()
        pool.acquire.return_value.__aenter__.return_value = conn

        # FIX: conn.transaction() must be synchronous and return an AsyncContextManager
        # We replace the default AsyncMock with a MagicMock for .transaction
        txn_cm = AsyncMock()
        txn_cm.__aenter__ = AsyncMock(return_value=None)
        txn_cm.__aexit__ = AsyncMock(return_value=None)

        conn.transaction = MagicMock(return_value=txn_cm)

        yield pool


@pytest.mark.asyncio
async def test_bg01_centralized_budget_control(mock_redis: MagicMock) -> None:
    """
    BG-01: Prevent Cloud Bill Shock.
    Enforce hard gate when daily cap is exceeded.
    """
    user_id = uuid.uuid4()
    settings.DAILY_BUDGET_LIMIT = 50.0

    # Scenario 1: Budget available
    # Redis eval returns [is_allowed, new_balance, is_new]
    # Allow 0.5 cost, resulting in 49.5 balance
    mock_redis.eval.return_value = [1, 49.5, 0]
    assert check_budget_guardrail(user_id, 0.5) is True

    # Scenario 2: Budget exceeded
    # Reject 1.0 cost because it exceeds limit. Return status 0.
    mock_redis.eval.return_value = [0, 50.5, 0]

    with pytest.raises(HTTPException) as exc:
        check_budget_guardrail(user_id, 1.0)

    assert exc.value.status_code == 402
    assert "limit exceeded" in exc.value.detail

    # Verify atomic call (eval) was used, NOT incrbyfloat
    assert not mock_redis.incrbyfloat.called
    mock_redis.eval.assert_called()


@pytest.mark.skipif(not HAS_PRESIDIO, reason="presidio-analyzer not installed")
@pytest.mark.asyncio
async def test_bg02_toxic_telemetry_prevention(mock_redis_telemetry: MagicMock) -> None:
    """
    BG-02: Zero PII in telemetry logs.
    Verify that async_log_telemetry pushes scrubbed data to Redis queue.
    """
    user_id = uuid.uuid4()
    input_text = "Call me at (555) 555-0199"

    from coreason_adlc_api.middleware.pii import scrub_pii_payload

    scrubbed_input = scrub_pii_payload(input_text)

    # Verify scrubbing logic first (isolated)
    assert "<REDACTED PHONE_NUMBER>" in scrubbed_input  # type: ignore

    # Now log it
    await async_log_telemetry(
        user_id=user_id,
        auc_id="proj-1",
        model_name="gpt-4",
        input_text=scrubbed_input,  # type: ignore
        output_text="Redacted response",
        metadata={"cost_usd": 0.01},
    )

    # Verify Redis push
    mock_redis_telemetry.rpush.assert_called_once()
    call_args = mock_redis_telemetry.rpush.call_args
    queue_name, json_payload = call_args[0]

    assert queue_name == "telemetry_queue"
    payload = json.loads(json_payload)

    assert payload["user_uuid"] == str(user_id)
    assert "<REDACTED" in payload["request_payload"]
    assert "555-0199" not in payload["request_payload"]


@pytest.mark.asyncio
async def test_fr_api_003_pessimistic_locking(mock_db_pool: MagicMock) -> None:
    """
    FR-API-003: Mutex on agent_drafts.
    """
    draft_id = uuid.uuid4()
    user_a = uuid.uuid4()
    user_b = uuid.uuid4()

    conn = mock_db_pool.acquire.return_value.__aenter__.return_value

    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    future = now + timedelta(seconds=30)

    # User B attempts to acquire, but A holds lock
    conn.fetchrow.return_value = {"locked_by_user": user_a, "lock_expiry": future}

    with pytest.raises(HTTPException) as exc:
        await acquire_draft_lock(draft_id, user_b, roles=[])

    assert exc.value.status_code == 423


@pytest.mark.asyncio
async def test_fr_api_004_safe_view_override(mock_db_pool: MagicMock) -> None:
    """
    FR-API-004: Manager Override (Safe View).
    """
    draft_id = uuid.uuid4()
    user_a = uuid.uuid4()
    manager_user = uuid.uuid4()

    conn = mock_db_pool.acquire.return_value.__aenter__.return_value

    from datetime import datetime, timedelta, timezone

    future = datetime.now(timezone.utc) + timedelta(seconds=30)

    conn.fetchrow.return_value = {"locked_by_user": user_a, "lock_expiry": future}

    mode = await acquire_draft_lock(draft_id, manager_user, roles=["MANAGER"])
    assert mode == AccessMode.SAFE_VIEW
    conn.execute.assert_not_called()
