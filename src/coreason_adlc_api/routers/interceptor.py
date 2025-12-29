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
from typing import Any, Dict, List, Optional, cast

import litellm
from fastapi import APIRouter, BackgroundTasks, Depends
from pydantic import BaseModel

from coreason_adlc_api.auth.identity import UserIdentity, parse_and_validate_token
from coreason_adlc_api.middleware.budget import check_budget_guardrail
from coreason_adlc_api.middleware.pii import scrub_pii_payload
from coreason_adlc_api.middleware.proxy import execute_inference_proxy
from coreason_adlc_api.middleware.telemetry import async_log_telemetry

router = APIRouter(prefix="/chat", tags=["interceptor"])


class ChatCompletionRequest(BaseModel):
    model: str
    messages: List[Dict[str, Any]]
    auc_id: str
    # Optional context for seed, etc.
    user_context: Optional[Dict[str, Any]] = None
    # Estimation can be passed by client or calculated.
    # Spec BG-01 says "Centralized Budget Control".
    # We should ideally calculate cost estimate locally (token counting).
    # But for now, we'll assume a fixed estimate or pass it.
    # FR-API-005: "If current + estimated > limit".
    # Let's assume a default small cost if not provided, or client provides it.
    estimated_cost: float = 0.01


def estimate_request_cost(model: str, messages: List[Dict[str, Any]]) -> float:
    """
    Estimates the cost of the request using LiteLLM's token counter and cost map.
    Assumes a default output buffer since we can't know response length yet.
    """
    try:
        # 1. Count Input Tokens
        input_tokens = litellm.token_counter(model=model, messages=messages)

        # 2. Get Model Cost Info
        # litellm.model_cost is a dict of model_name -> cost_dict
        # We need to handle aliases or lookup failures safely
        try:
            cost_info = litellm.model_cost.get(model)
            # Fallback for exact match failure (litellm usually handles this but accessing dict directly might fail)
            if not cost_info:
                # Try to force a lookup if possible, or fallback
                # For now, we'll assume if it's not in the map, we use default
                raise ValueError("Model cost not found")

            input_cost_per_token = cost_info.get("input_cost_per_token", 0.0)
            output_cost_per_token = cost_info.get("output_cost_per_token", 0.0)
        except Exception:
            # Fallback defaults (approximate to GPT-3.5 levels if unknown)
            input_cost_per_token = 0.0000005
            output_cost_per_token = 0.0000015

        # 3. Estimate Output Tokens (Conservative Buffer)
        # We don't know how many tokens the model will generate.
        # Let's assume a safe buffer, e.g., 500 tokens.
        estimated_output_tokens = 500

        total_cost = (input_tokens * input_cost_per_token) + (estimated_output_tokens * output_cost_per_token)
        return total_cost

    except Exception:
        # Fallback to a safe default if estimation fails completely
        return 0.01


@router.post("/completions")
async def chat_completions(
    request: ChatCompletionRequest,
    background_tasks: BackgroundTasks,
    user: UserIdentity = Depends(parse_and_validate_token),
) -> Dict[str, Any]:
    """
    The Interceptor: Budget -> Proxy -> Scrub -> Log.
    """
    start_time = time.time()

    # 1. Budget Gatekeeper
    # We ignore the client's estimated_cost for the blocking check to prevent bypass.
    # Instead, we calculate it server-side.
    server_estimated_cost = estimate_request_cost(request.model, request.messages)

    # This is blocking.
    check_budget_guardrail(user.oid, server_estimated_cost)

    # 2. PII Scrubbing (Input)
    # Spec says: "The API must pass the raw request_payload... to Presidio."
    # "Replace detected entities... with <REDACTED>."
    # "Scope: Memory only (do not write raw text to disk)."
    # We scrub input BEFORE logging, but do we scrub before sending to LLM?
    # Spec: "Proxy & Determinism: Forward the request to the model provider."
    # Spec: "In-Memory PII Scrubbing... Replace detected entities... Scope: Memory only"
    # Usually we want to scrub input sent to LLM if it's external (Data Leakage Prevention).
    # "The coreason-adlc-api acts as the Governance Enforcement Layer..."
    # "Toxic Telemetry Prevention... scrub data in-stream before it rests in the database."
    # It doesn't explicitly say "Scrub before sending to LLM".
    # It says "Logic Flow: Request -> Budget -> LiteLLM -> Presidio -> Redis".
    # This implies Presidio runs AFTER LiteLLM?
    # Table FR-API-007: "Pass raw request... and response... to Presidio."
    # Table FR-API-008: "Push Scrubbed payloads... to Redis."
    # This implies we scrub primarily for LOGGING (Telemetry).
    # If we scrubbed before LiteLLM, the LLM wouldn't work well (context lost).
    # Unless "Data Loss Prevention" is the goal.
    # BG-02 says "Eliminate legal liability of storing PII in permanent logs."
    # So the main goal is scrubbing LOGS.
    # So we send RAW to LLM, but log SCRUBBED.

    # 3. Inference Proxy
    # We send raw messages to LLM.
    try:
        response = await execute_inference_proxy(
            messages=request.messages,
            model=request.model,
            auc_id=request.auc_id,
            user_context=request.user_context,
        )
    except Exception:
        # If proxy fails, we might still want to log the attempt?
        # But for now, we just raise.
        raise

    # 4. Extract Response Text
    # LiteLLM returns OpenAI format.
    try:
        response_content = response["choices"][0]["message"]["content"]
    except (KeyError, TypeError, IndexError):
        response_content = ""

    # 5. PII Scrubbing (for Telemetry)
    # We scrub both Request (Input) and Response (Output)
    # We need to flatten messages to string for scrubbing/logging?
    # Or scrub structure?
    # `scrub_pii_payload` takes `str`.
    # Let's simple-concat input messages for logging.
    input_text = "\n".join([m.get("content", "") for m in request.messages])

    scrubbed_input = scrub_pii_payload(input_text) or ""
    scrubbed_output = scrub_pii_payload(response_content) or ""

    # 6. Async Telemetry Logging
    latency_ms = int((time.time() - start_time) * 1000)
    # Calculate real cost from usage if available
    real_cost = request.estimated_cost  # Default to estimate
    try:
        real_cost = litellm.completion_cost(completion_response=response)
    except Exception:
        pass  # Fallback to estimate if calculation fails

    background_tasks.add_task(
        async_log_telemetry,
        user_id=user.oid,
        auc_id=request.auc_id,
        model_name=request.model,
        input_text=scrubbed_input,
        output_text=scrubbed_output,
        metadata={"cost_usd": real_cost, "latency_ms": latency_ms},
    )

    # Return raw response to user?
    # Or scrubbed?
    # "acts as Governance Enforcement Layer..."
    # BG-02: "Eliminate legal liability of storing PII in permanent logs."
    # Does NOT say "Prevent User from seeing PII".
    # Usually users are allowed to see what they generated.
    # But if "Toxic Telemetry Prevention" is the goal, then we only scrub logs.
    # However, if "Data Plane" (Tier 3) is sensitive...
    # I will assume we return the RAW response to the user (Client), but scrub the LOGS.
    # Wait, if we return raw response, then the client has PII.
    # "The Client (Streamlit) connects strictly to Middleware."
    # If the user put PII in, they get PII out.
    # The requirement emphasizes "storing PII in permanent logs".
    # I will return the raw response object from LiteLLM.

    return cast(Dict[str, Any], response)
