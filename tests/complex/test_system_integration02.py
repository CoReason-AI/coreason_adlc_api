# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import datetime
import json
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.routers.interceptor import ChatCompletionRequest, chat_completions
from coreason_adlc_api.routers.vault import create_or_update_secret
from coreason_adlc_api.routers.workbench import create_new_draft
from coreason_adlc_api.vault.schemas import CreateSecretRequest
from coreason_adlc_api.workbench.schemas import DraftCreate
from fastapi import HTTPException
from presidio_analyzer import RecognizerResult


@pytest.fixture
def mock_pool() -> Generator[MagicMock, None, None]:
    pool = MagicMock()
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
    conn.execute = AsyncMock()
    conn.fetch = AsyncMock()

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)

    pool.acquire.return_value = conn_cm

    # Transaction Context Manager
    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = txn_cm

    # Pool methods
    pool.fetchrow = AsyncMock()
    pool.execute = AsyncMock()
    pool.fetch = AsyncMock()

    # Patch in all places likely to use it
    with (
        patch("coreason_adlc_api.db.get_pool", return_value=pool),
        patch("coreason_adlc_api.workbench.service.get_pool", return_value=pool),
        patch("coreason_adlc_api.vault.service.get_pool", return_value=pool),
        patch("coreason_adlc_api.auth.identity.get_pool", return_value=pool),
    ):
        yield pool


@pytest.fixture
def mock_redis() -> Generator[MagicMock, None, None]:
    redis = MagicMock()
    # Mock budget calls (Synchronous)
    redis.get.return_value = None  # No current spend
    redis.incrbyfloat.return_value = 0.5
    redis.decrby.return_value = None
    redis.expire.return_value = None
    # Mock telemetry calls (Synchronous)
    redis.rpush.return_value = 1

    with (
        patch("coreason_adlc_api.middleware.budget.get_redis_client", return_value=redis),
        patch("coreason_adlc_api.middleware.telemetry.get_redis_client", return_value=redis),
    ):
        yield redis


@pytest.fixture
def mock_litellm() -> Generator[MagicMock, None, None]:
    with patch("coreason_adlc_api.routers.interceptor.execute_inference_proxy", new_callable=AsyncMock) as mock_proxy:
        mock_proxy.return_value = {
            "choices": [{"message": {"content": "This is the AI response with PII: 555-0199"}}],
            "usage": {"total_tokens": 100}
        }
        with patch("coreason_adlc_api.routers.interceptor.litellm.completion_cost", return_value=0.002):
            yield mock_proxy


@pytest.fixture
def mock_pii_analyzer() -> Generator[MagicMock, None, None]:
    # Mock the internal logic of scrub_pii_payload by patching PIIAnalyzer
    # OR better, patch scrub_pii_payload directly if we want to trust it works (unit tests cover it)
    # BUT the plan said: "Mock PIIAnalyzer ... simulate PII detection"
    # So let's patch the AnalyzerEngine used by PIIAnalyzer.

    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine") as mock_engine_cls:
        mock_instance = mock_engine_cls.return_value

        def analyze_side_effect(text: str, **kwargs: Any) -> list[RecognizerResult]:
            results = []
            if "555-0199" in text:
                 # Calculate start/end based on text find
                 start = text.find("555-0199")
                 results.append(RecognizerResult(entity_type="PHONE_NUMBER", start=start, end=start+8, score=1.0))
            return results

        mock_instance.analyze.side_effect = analyze_side_effect

        # Reset Singleton
        from coreason_adlc_api.middleware.pii import PIIAnalyzer
        PIIAnalyzer._instance = None
        yield mock_instance
        PIIAnalyzer._instance = None


@pytest.mark.asyncio
async def test_full_workflow_integration(
    mock_pool: MagicMock,
    mock_redis: MagicMock,
    mock_litellm: MagicMock,
    mock_pii_analyzer: MagicMock,
) -> None:
    """
    Simulate a full user journey:
    1. User (Authorized) creates a Draft (Workbench).
    2. User adds a Secret (Vault).
    3. User chats with AI (Interceptor) -> Checks Budget, Calls LLM, Scrubs PII, Logs Telemetry.
    """

    # Setup User & Permissions
    user_oid = uuid4()
    group_oid = uuid4()
    auc_id = "project-alpha"
    identity = UserIdentity(oid=user_oid, email="user@test.com", groups=[group_oid], full_name="Test User")

    # 1. MOCK RBAC: map_groups_to_projects
    # We need to patch this in workbench, vault AND interceptor?
    # Interceptor currently doesn't call map_groups_to_projects in the code provided?
    # Let's check `src/coreason_adlc_api/routers/interceptor.py`.
    # It takes `ChatCompletionRequest` with `auc_id`.
    # But does it check permissions?
    # The code I read earlier:
    # `async def chat_completions(..., user: UserIdentity = Depends(parse_and_validate_token)):`
    # It does NOT seem to call `map_groups_to_projects` in the snippet I saw!
    # Wait, `workbench` and `vault` DO.
    # Ideally Interceptor SHOULD too. If it doesn't, that's a security hole (IDOR), but here we are testing existing behavior.
    # The memory says: "RBAC... enforced by verifying that the target auc_id exists in the list returned by map_groups_to_projects".
    # If Interceptor doesn't do it, I shouldn't assert it does unless I fix it (which is out of scope unless it's a bug fix task).
    # But let's look at `interceptor.py` again.
    # It was: `check_budget_guardrail` -> `execute_inference_proxy` -> `log_telemetry`.
    # No explicit `map_groups_to_projects` check in the snippet.
    # I will proceed assuming Workbench and Vault check it.

    with patch("coreason_adlc_api.routers.workbench.map_groups_to_projects", new_callable=AsyncMock) as mock_map_wb, \
         patch("coreason_adlc_api.routers.vault.map_groups_to_projects", new_callable=AsyncMock) as mock_map_vault:

        mock_map_wb.return_value = [auc_id]
        mock_map_vault.return_value = [auc_id]

        # --- Step 1: Create Draft ---
        draft_req = DraftCreate(auc_id=auc_id, title="Integration Draft", oas_content={})

        # Mock DB calls for create_draft
        # service.create_draft inserts into agent_drafts
        mock_pool.fetchrow.return_value = {
            "draft_id": uuid4(),
            "user_uuid": user_oid,
            "auc_id": auc_id,
            "title": "Integration Draft",
            "oas_content": {},
            "created_at": datetime.datetime.now(),
            "updated_at": datetime.datetime.now(),
        }

        draft_resp = await create_new_draft(draft_req, identity)
        assert draft_resp.title == "Integration Draft"
        assert draft_resp.auc_id == auc_id

        # --- Step 2: Store Secret ---
        secret_req = CreateSecretRequest(
            auc_id=auc_id,
            service_name="openai",
            raw_api_key="sk-test-12345"
        )

        # Mock DB for store_secret
        # It runs: encryption -> insert into vault.secrets
        # We need to mock `mock_pool.execute` or `fetchrow` depending on implementation.
        # Assuming `store_secret` returns secret_id.
        # Let's mock the internal `store_secret` service function if complex, OR just mock DB.
        # `vault/service.py` logic: encrypt -> insert returning secret_id.
        mock_pool.fetchrow.return_value = {"secret_id": uuid4()} # reusing mock, ensure side_effect management if needed

        secret_resp = await create_or_update_secret(secret_req, identity)
        assert secret_resp.service_name == "openai"

        # --- Step 3: Chat Completion (Interceptor) ---
        # Input has PII: "My phone is 555-0199"
        input_msg = "My phone is 555-0199"
        chat_req = ChatCompletionRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": input_msg}],
            auc_id=auc_id,
            estimated_cost=0.01
        )

        # Mock Budget: check_budget_guardrail calls Redis
        # mocked in fixture

        # Execute
        response = await chat_completions(chat_req, identity)

        # Assertions

        # 1. Proxy called with RAW input (No Scrubbing before LLM)
        mock_litellm.assert_called_once()
        call_kwargs = mock_litellm.call_args[1]
        assert call_kwargs["messages"][0]["content"] == input_msg

        # 2. Response returned to user is RAW (as per my reasoning)
        # Mock returned: "This is the AI response with PII: 555-0199"
        assert response["choices"][0]["message"]["content"] == "This is the AI response with PII: 555-0199"

        # 3. Telemetry Logged SCRUBBED input and output
        # Telemetry puts to Redis list "telemetry_queue"
        # We need to find the `rpush` call.
        # Note: `async_log_telemetry` -> `client.rpush("telemetry_queue", json_data)`

        assert mock_redis.rpush.called
        telemetry_call = mock_redis.rpush.call_args
        # args: (queue_name, data)
        assert telemetry_call[0][0] == "telemetry_queue"
        logged_data = json.loads(telemetry_call[0][1])

        # Verify Scrubbing in Logs
        # Input: "My phone is 555-0199" -> "My phone is <REDACTED PHONE_NUMBER>"
        assert "<REDACTED PHONE_NUMBER>" in logged_data["request_payload"]
        assert "555-0199" not in logged_data["request_payload"]

        # Output: "This is the AI response with PII: 555-0199" -> "... <REDACTED ...>"
        assert "<REDACTED PHONE_NUMBER>" in logged_data["response_payload"]
        assert "555-0199" not in logged_data["response_payload"]

        # Verify Cost/Latency
        assert logged_data["cost_usd"] == 0.002
        assert logged_data["auc_id"] == auc_id


@pytest.mark.asyncio
async def test_budget_enforcement_in_workflow(
    mock_redis: MagicMock,
    mock_litellm: MagicMock
) -> None:
    """
    Test that the workflow is halted if budget is exceeded.
    """
    user_oid = uuid4()
    auc_id = "project-broke"
    identity = UserIdentity(oid=user_oid, email="broke@test.com", groups=[], full_name="Broke User")

    chat_req = ChatCompletionRequest(
        model="gpt-4",
        messages=[{"role": "user", "content": "hi"}],
        auc_id=auc_id,
        estimated_cost=100.0
    )

    # Mock Redis to simulate Over Budget
    # check_budget_guardrail logic:
    # current = get(user_key)
    # if current > limit: raise 402

    # We need to simulate that `incrbyfloat` returns a value > limit OR `get` returns high value.
    # It depends on implementation. Optimistic reservation usually does incr first.
    # "Budget enforcement uses an optimistic 'reservation' strategy (increment then rollback)"
    # So it calls incrbyfloat.
    # Let's set the return value of incrbyfloat to be very high (e.g. $1000)
    # Assuming default limit is small (e.g. $10 or $50)

    mock_redis.incrbyfloat.return_value = 9999.0

    # Also need to mock 'decrby' or 'incrbyfloat(-cost)' if it rolls back?
    # If 402 is raised, does it rollback? Yes, usually.

    with pytest.raises(HTTPException) as exc:
        await chat_completions(chat_req, identity)

    assert exc.value.status_code == 402
    assert "Daily budget limit exceeded." in str(exc.value.detail)

    # Verify Proxy was NOT called
    mock_litellm.assert_not_called()

    # Verify rollback happened (decrement)
    # It might use incrbyfloat with negative value or decrby
    # Check calls
    assert mock_redis.incrbyfloat.call_count >= 1
    # First call was the reservation (+100.0) -> returned 9999.0
    # Next call should be rollback (-100.0)

    # We can inspect args
    calls = mock_redis.incrbyfloat.call_args_list
    assert len(calls) >= 2
    # Last call should be negative cost
    assert calls[-1][0][1] < 0
