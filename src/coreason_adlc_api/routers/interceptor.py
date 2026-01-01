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

import litellm
from coreason_veritas.auditor import IERLogger
from coreason_veritas.sanitizer import scrub_pii_payload
from fastapi import APIRouter, BackgroundTasks, Depends
from opentelemetry import trace

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.middleware.budget import BudgetService
from coreason_adlc_api.middleware.proxy import InferenceProxyService
from coreason_adlc_api.routers.schemas import ChatCompletionRequest, ChatCompletionResponse

router = APIRouter(prefix="/chat", tags=["interceptor"])


def get_budget_service() -> BudgetService:
    return BudgetService()


def get_proxy_service() -> InferenceProxyService:
    return InferenceProxyService()


@router.post("/completions", response_model=ChatCompletionResponse)
async def chat_completions(
    request: ChatCompletionRequest,
    background_tasks: BackgroundTasks,
    user: UserIdentity = Depends(parse_and_validate_token),
    budget_service: BudgetService = Depends(get_budget_service),
    proxy_service: InferenceProxyService = Depends(get_proxy_service),
) -> ChatCompletionResponse:
    """
    The Interceptor: Budget -> Proxy -> Scrub -> Log.
    """
    start_time = time.time()

    # Convert Pydantic models to list of dicts for internal use
    # We use model_dump for V2, but let's check Pydantic version if needed.
    # Assuming V2 based on pyproject.toml
    messages_dicts = [m.model_dump(exclude_none=True) for m in request.messages]

    # 1. Budget Gatekeeper
    # We calculate estimated cost server-side to prevent bypass.
    # Offloaded to thread in proxy service
    server_estimated_cost = await proxy_service.estimate_request_cost(request.model, messages_dicts)

    # This is blocking (redis call), but async
    await budget_service.check_budget_guardrail(user.oid, server_estimated_cost)

    # 2. PII Scrubbing (Input) - Telemetry only
    # See previous notes: we send RAW to LLM for functionality, scrub logs for compliance.

    # 3. Inference Proxy
    # We send raw messages to LLM.
    try:
        response = await proxy_service.execute_inference(
            messages=messages_dicts,
            model=request.model,
            auc_id=request.auc_id,
            user_context=request.user_context,
        )
    except Exception:
        raise

    # 4. Extract Response Text
    try:
        response_content = response["choices"][0]["message"]["content"]
    except (KeyError, TypeError, IndexError):
        response_content = ""

    # 5. PII Scrubbing (for Telemetry)
    # Flatten messages to string for scrubbing/logging
    input_text = "\n".join([m.get("content", "") for m in messages_dicts])

    # Veritas scrubber is synchronous. We run it to ensure compliance logic executes,
    # even if IERLogger doesn't currently consume the preview in this version.
    scrub_pii_payload(input_text)
    scrub_pii_payload(response_content)

    # 6. Async Telemetry Logging via Veritas IERLogger
    latency_ms = int((time.time() - start_time) * 1000)

    # Calculate real cost from usage if available, else estimate
    real_cost = server_estimated_cost
    try:
        # We can't use litellm.completion_cost on a raw dict easily without the right object structure
        # But litellm handles dicts often.
        real_cost = litellm.completion_cost(completion_response=response)
    except Exception:
        pass

    # Extract Token Usage
    usage = response.get("usage", {})
    input_tokens = usage.get("prompt_tokens", 0)
    output_tokens = usage.get("completion_tokens", 0)

    # Extract Trace ID
    span = trace.get_current_span()
    trace_id = format(span.get_span_context().trace_id, "032x")

    IERLogger().log_llm_transaction(
        trace_id=trace_id,
        user_id=str(user.oid),
        project_id=request.auc_id,
        model=request.model,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cost_usd=real_cost,
        latency_ms=latency_ms,
    )

    return ChatCompletionResponse(**response)
