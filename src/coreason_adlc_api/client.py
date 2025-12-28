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
import os
from typing import Any

import httpx

from coreason_adlc_api.client_auth import ClientAuthManager
from coreason_adlc_api.exceptions import (
    AuthenticationError,
    BudgetExceededError,
    ClientError,
    ComplianceViolationError,
    CoreasonError,
    RateLimitError,
    ServerError,
    ServiceUnavailableError,
)


class CoreasonClient:
    """
    Singleton Facade for the Coreason ADLC API Client.
    Synchronous implementation for compatibility with Streamlit and scripts.
    """

    _instance = None

    def __new__(cls, *args: object, **kwargs: object) -> "CoreasonClient":
        if not cls._instance:
            cls._instance = super(CoreasonClient, cls).__new__(cls)
        return cls._instance

    def __init__(self, base_url: str | None = None) -> None:
        # Since this is a singleton, avoid re-initialization if already set up
        if hasattr(self, "client"):
            return

        # Ensure base_url is strictly a string for httpx, even if None passed (handled by os.getenv default)
        # We explicitly cast to str or handle None case in the 'or' to satisfy both runtime and mypy
        url_from_env = os.getenv("COREASON_API_URL", "http://localhost:8000")
        self.base_url = base_url or (url_from_env if url_from_env is not None else "http://localhost:8000")

        self.auth = ClientAuthManager()

        # Initialize httpx Client with event hook for authentication
        self.client = httpx.Client(
            base_url=self.base_url,
            event_hooks={"request": [self._inject_auth_header]},
            timeout=30.0,  # Reasonable default
        )

    def _inject_auth_header(self, request: httpx.Request) -> None:
        """
        Interceptor to inject Authorization header if token is available.
        """
        # Skip auth for the auth endpoints themselves to avoid circular issues
        # although usually harmless, it's cleaner.
        path = request.url.path
        if path.startswith("/auth/"):
            return

        token = self.auth.get_token()
        if token:
            request.headers["Authorization"] = f"Bearer {token}"

    def set_project(self, auc_id: str) -> None:
        """
        Sets the Project ID (AUC ID) for the session context.
        This header will be included in all subsequent requests.
        """
        self.client.headers["X-Coreason-Project-ID"] = auc_id

    def close(self) -> None:
        """
        Closes the underlying httpx client.
        """
        self.client.close()

    def _handle_response(self, response: httpx.Response) -> httpx.Response:
        """
        Inspects the response status code and body to raise specific CoreasonErrors.
        If the response is successful, it is returned.
        """
        if response.is_success:
            return response

        # Try to parse the error message from the body
        message = ""
        try:
            data = response.json()
            if isinstance(data, dict):
                # Search for common error keys
                message = data.get("detail") or data.get("message") or data.get("error") or ""
        except json.JSONDecodeError:
            pass

        if not message:
            # Fallback to the raw text body or standard HTTP reason phrase
            message = response.text or response.reason_phrase

        status = response.status_code

        if status in (401, 403):
            raise AuthenticationError(message, response)
        elif status == 402:
            raise BudgetExceededError(message, response)
        elif status == 422:
            raise ComplianceViolationError(message, response)
        elif status == 429:
            raise RateLimitError(message, response)
        elif 400 <= status < 500:
            raise ClientError(message, response)
        elif status in (502, 503, 504):
            raise ServiceUnavailableError(message, response)
        elif 500 <= status < 600:
            raise ServerError(message, response)

        # Fallback for anything else that httpx considers an error (should be covered above if is_error is true)
        raise CoreasonError(message, response)

    def request(self, method: str, url: str, **kwargs: Any) -> httpx.Response:
        """
        Wrapper for the underlying httpx client request.
        Handles exceptions and maps them to domain-specific CoreasonErrors.

        Returns:
            httpx.Response: The raw response object (for header access, etc).
        """
        response = self.client.request(method, url, **kwargs)
        return self._handle_response(response)

    def get(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience wrapper for GET requests."""
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience wrapper for POST requests."""
        return self.request("POST", url, **kwargs)

    def put(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience wrapper for PUT requests."""
        return self.request("PUT", url, **kwargs)

    def delete(self, url: str, **kwargs: Any) -> httpx.Response:
        """Convenience wrapper for DELETE requests."""
        return self.request("DELETE", url, **kwargs)

    def validate_draft(self, draft: dict[str, Any]) -> list[str]:
        """
        Validates a draft against PII and Budget constraints remotely.
        Returns a list of issues found (empty list if valid).
        """
        response = self.post("/workbench/validate", json=draft)
        data = response.json()
        return data.get("issues", [])
