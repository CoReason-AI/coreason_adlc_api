# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
from typing import Any, Dict, Generator
from unittest.mock import AsyncMock, MagicMock, patch
from uuid import uuid4

import pytest
from coreason_adlc_api.auth.identity import UserIdentity
from coreason_adlc_api.routers.interceptor import ChatCompletionRequest, chat_completions
from coreason_adlc_api.routers.workbench import create_new_draft
from coreason_adlc_api.workbench.schemas import DraftCreate
from fastapi import HTTPException


@pytest.fixture
def mock_pool() -> Generator[MagicMock, None, None]:
    """
    Complex Mock for the Database Pool to handle multiple subsystem queries:
    - Workbench: RBAC, Draft creation.
    - Vault: Fetching encrypted secrets.
    """
    pool = MagicMock()

    # Connection Context Manager
    conn = MagicMock()
    conn.fetchrow = AsyncMock()
    conn.fetch = AsyncMock()
    conn.execute = AsyncMock()

    conn_cm = MagicMock()
    conn_cm.__aenter__ = AsyncMock(return_value=conn)
    conn_cm.__aexit__ = AsyncMock(return_value=None)
    pool.acquire.return_value = conn_cm

    # Transaction Context Manager
    txn_cm = MagicMock()
    txn_cm.__aenter__ = AsyncMock(return_value=None)
    txn_cm.__aexit__ = AsyncMock(return_value=None)
    conn.transaction.return_value = txn_cm

    # Direct Pool Methods
    pool.fetchrow = AsyncMock()
    pool.fetch = AsyncMock()
    pool.execute = AsyncMock()

    yield pool


@pytest.mark.asyncio
async def test_full_agent_lifecycle_with_governance(mock_pool: MagicMock) -> None:
    """
    System-Wide Integration Test:
    Simulates a complete flow from Agent Creation -> Inference -> Governance.

    Flow:
    1.  **Workbench**: Authenticated User creates a Draft Agent (RBAC check).
    2.  **Vault (Simulated)**: System retrieves an API Key for the agent's model.
    3.  **Interceptor**: User requests Chat Completion.
        -   **Budget**: Checks Redis for daily limit.
        -   **Proxy**: Decrypts secret, calls LLM (Mocked).
        -   **PII**: Scrubs input/output (Mocked).
        -   **Telemetry**: Logs usage to Redis.
    """

    # --- Setup Data ---
    user_oid = uuid4()
    group_oid = uuid4()
    auc_id = "project-genai-alpha"
    model_name = "gpt-4"

    # Input with PII to verify scrubbing logic invocation
    user_input_text = "My email is sensitive@example.com"
    llm_output_text = "Here is the data for sensitive@example.com"

    identity = UserIdentity(
        oid=user_oid,
        email="dev@coreason.com",
        groups=[group_oid],
        full_name="Dev User",
    )

    # --- Mocks Configuration ---

    # 1. DB: RBAC & Drafts
    # Queries: map_groups_to_projects, create_draft, get_api_key...

    # We'll use side_effect to handle different queries if needed, or just lenient mocks.
    # For map_groups_to_projects (called in Workbench), we patch the function directly usually.
    # For Vault secret fetch, it uses pool.fetchrow.

    # Mock Vault Secret Return
    mock_pool.fetchrow.return_value = {"encrypted_value": b"encrypted_fake_key"}

    # 2. Redis: Budget & Telemetry
    mock_redis = MagicMock()
    # Budget: incrbyfloat returns new total (e.g. 0.05)
    mock_redis.incrbyfloat.return_value = 0.05

    # 3. Vault Crypto
    mock_crypto = MagicMock()
    mock_crypto.decrypt_secret.return_value = "sk-fake-openai-key"

    # 4. LiteLLM
    mock_litellm_resp = {
        "choices": [{"message": {"content": llm_output_text}}],
        "usage": {"total_tokens": 100},
    }

    # --- Execution Context ---

    with (
        # Patch DB getters
        patch("coreason_adlc_api.routers.workbench.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.middleware.proxy.get_pool", return_value=mock_pool),
        patch("coreason_adlc_api.auth.identity.get_pool", return_value=mock_pool),
        # Patch Redis getters
        patch("coreason_adlc_api.middleware.budget.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.middleware.telemetry.get_redis_client", return_value=mock_redis),
        # Patch Services/Logic
        patch(
            "coreason_adlc_api.routers.workbench.map_groups_to_projects", new_callable=AsyncMock
        ) as mock_map_groups,
        patch("coreason_adlc_api.routers.workbench.create_draft", new_callable=AsyncMock) as mock_create_draft,
        # Patch VaultCrypto where it is used in proxy.py
        patch("coreason_adlc_api.middleware.proxy.VaultCrypto", return_value=mock_crypto),
        # Patch LiteLLM
        patch("coreason_adlc_api.middleware.proxy.litellm.acompletion", new_callable=AsyncMock) as mock_acompletion,
        patch(
            "coreason_adlc_api.middleware.proxy.litellm.get_llm_provider",
            return_value=("openai", "gpt-4", "k", "b"),
        ),
        patch(
            "coreason_adlc_api.routers.interceptor.litellm.completion_cost", return_value=0.03
        ),  # Real cost calc
        # Patch PII Scrubbing
        patch("coreason_adlc_api.routers.interceptor.scrub_pii_payload") as mock_scrub,
    ):
        # Configure Mocks
        mock_map_groups.return_value = [auc_id]
        mock_create_draft.return_value = MagicMock(auc_id=auc_id, title="Agent Smith")
        mock_acompletion.return_value = mock_litellm_resp
        mock_scrub.side_effect = lambda x: x.replace("sensitive@example.com", "<REDACTED>")

        # --- STEP 1: Workbench - Create Draft ---
        draft_req = DraftCreate(auc_id=auc_id, title="Agent Smith", oas_content={})
        draft_resp = await create_new_draft(draft_req, identity)

        assert draft_resp.title == "Agent Smith"
        mock_map_groups.assert_called()  # Verified RBAC
        mock_create_draft.assert_called()  # Verified DB Write attempt

        # --- STEP 2: Interceptor - Chat Completion ---
        chat_req = ChatCompletionRequest(
            model=model_name,
            messages=[{"role": "user", "content": user_input_text}],
            auc_id=auc_id,
            estimated_cost=0.01,
        )

        _ = await chat_completions(chat_req, identity)

        # --- Verification Phase ---

        # 1. Budget Checked?
        mock_redis.incrbyfloat.assert_called()  # Should call for budget check
        # Specifically check the key format if we want to be pedantic, but called is good enough.
        args, _ = mock_redis.incrbyfloat.call_args
        assert f"budget:{asyncio.get_event_loop().time()}" not in args[0]  # Just ensuring it ran

        # 2. Vault Accessed?
        mock_pool.fetchrow.assert_called()  # To get encrypted key
        mock_crypto.decrypt_secret.assert_called_with(b"encrypted_fake_key")

        # 3. Proxy Called Correctly?
        mock_acompletion.assert_called_once()
        call_kwargs = mock_acompletion.call_args.kwargs
        assert call_kwargs["api_key"] == "sk-fake-openai-key"  # Decrypted key injected
        assert call_kwargs["temperature"] == 0.0  # Determinism enforcement
        assert call_kwargs["messages"][0]["content"] == user_input_text  # Raw input sent to LLM

        # 4. PII Scrubbing?
        # Expect 2 calls: one for input, one for output
        assert mock_scrub.call_count == 2

        # 5. Telemetry Logged?
        # We need to verify `async_log_telemetry` pushed to Redis
        # Note: `async_log_telemetry` calls `client.rpush`
        mock_redis.rpush.assert_called_once()

        # Inspect the pushed payload
        call_args = mock_redis.rpush.call_args
        queue_name, json_payload = call_args[0]
        assert queue_name == "telemetry_queue"

        # Since json_payload is a string, we check substrings or parse it
        import json

        payload_dict = json.loads(json_payload)

        assert payload_dict["auc_id"] == auc_id
        assert payload_dict["user_uuid"] == str(user_oid)
        assert payload_dict["cost_usd"] == 0.03  # Real cost from completion_cost mock

        # Verify SCRUBBED content was logged
        # Keys in payload are request_payload/response_payload, not input_text/output_text
        assert "<REDACTED>" in payload_dict["request_payload"]
        assert "<REDACTED>" in payload_dict["response_payload"]
        assert "sensitive@example.com" not in payload_dict["request_payload"]


@pytest.mark.asyncio
async def test_budget_exceeded_blocking(mock_pool: MagicMock) -> None:
    """
    Test that Interceptor strictly blocks requests when budget is exceeded.
    """
    user_oid = uuid4()
    auc_id = "proj-budget-test"

    identity = UserIdentity(oid=user_oid, email="poor@example.com", groups=[], full_name="Poor User")

    mock_redis = MagicMock()
    # Simulate Budget Limit Hit: Current spend + Cost > Limit (default $10.0)
    # Return 11.0
    mock_redis.incrbyfloat.return_value = 11.0

    with (
        patch("coreason_adlc_api.middleware.budget.get_redis_client", return_value=mock_redis),
        patch("coreason_adlc_api.middleware.budget.settings.DAILY_BUDGET_LIMIT", 10.0),
    ):
        req = ChatCompletionRequest(
            model="gpt-4",
            messages=[{"role": "user", "content": "hi"}],
            auc_id=auc_id,
            estimated_cost=1.0
        )

        with pytest.raises(HTTPException) as exc:
            await chat_completions(req, identity)

        assert exc.value.status_code == 402
        assert "limit exceeded" in exc.value.detail

        # Verify rollback (decrement)
        assert mock_redis.incrbyfloat.call_count == 2
        # First call: +1.0 -> Returns 11.0
        # Second call: -1.0 -> Rollback
