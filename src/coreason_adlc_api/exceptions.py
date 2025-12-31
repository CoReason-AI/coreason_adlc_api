# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import httpx


class CoreasonError(Exception):
    """Base exception for all Coreason SDK errors."""

    def __init__(self, message: str, response: httpx.Response | None = None) -> None:
        super().__init__(message)
        self.message = message
        self.response = response
        self.status_code = response.status_code if response is not None else None


class ClientError(CoreasonError):
    """Exception raised for 4xx Client Errors."""

    pass


class ServerError(CoreasonError):
    """Exception raised for 5xx Server Errors."""

    pass


class AuthenticationError(ClientError):
    """Exception raised for 401/403 Authentication Errors."""

    pass

class AccessDeniedError(AuthenticationError):
    """Exception raised for 403 Forbidden Errors (specific permission denied)."""
    pass

class ResourceNotFoundError(ClientError):
    """Exception raised for 404 Not Found Errors."""
    pass

class DraftLockedError(ClientError):
    """Exception raised when a draft is locked by another user."""
    pass

class BudgetExceededError(ClientError):
    """Exception raised for 402 Budget Exceeded Errors."""

    pass


class ComplianceViolationError(ClientError):
    """Exception raised for 422 Compliance/Policy Violation Errors."""

    pass


class RateLimitError(ClientError):
    """Exception raised for 429 Rate Limit Errors."""

    pass


class ServiceUnavailableError(ServerError):
    """Exception raised for 502/503/504 Service Unavailable Errors."""

    pass
