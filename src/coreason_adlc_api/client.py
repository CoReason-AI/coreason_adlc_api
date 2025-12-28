# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import os

import httpx

from coreason_adlc_api.client_auth import ClientAuthManager


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
