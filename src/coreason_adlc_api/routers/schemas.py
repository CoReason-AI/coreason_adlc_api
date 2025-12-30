# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class ChatMessage(BaseModel):
    """
    Standardizes the message structure for Chat Completions.
    Typically: {"role": "user", "content": "..."}
    """

    role: str
    content: str
    name: Optional[str] = None


class ChatCompletionRequest(BaseModel):
    """
    Request model for the Interceptor / Chat Completions endpoint.
    Enforces strict typing on messages.
    """

    model: str
    messages: List[ChatMessage]
    auc_id: str
    user_context: Optional[Dict[str, Any]] = None
    # Estimation can be passed by client or calculated.
    estimated_cost: float = 0.01


class ChatCompletionResponse(BaseModel):
    """
    Standardized response model.
    Assuming standard OpenAI-like response format.
    We use Dict[str, Any] for the full flexible response,
    but we could lock this down further if needed.
    For now, we just ensure it's a valid dict.
    """
    # In reality, this mirrors the OpenAI Choice/Usage structure.
    # We can leave it open or define it fully.
    # Given the 'Best Practices' requirement, let's keep it flexible but explicit.
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[Dict[str, Any]]
    usage: Optional[Dict[str, Any]] = None
