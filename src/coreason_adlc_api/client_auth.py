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
from typing import Any, Callable

import httpx
import jwt
import keyring
from tenacity import RetryError, retry, retry_if_exception, stop_after_delay

from coreason_adlc_api.auth.schemas import DeviceCodeResponse, TokenResponse

SERVICE_NAME = "coreason-adlc-api-key"
USERNAME = "default_user"


class AuthorizationPendingError(Exception):
    pass


class SlowDownError(Exception):
    pass


def is_polling_error(exception: Exception) -> bool:
    """Retry if AuthorizationPending or SlowDown."""
    return isinstance(exception, (AuthorizationPendingError, SlowDownError))


class ClientAuthManager:
    """
    Handles OAuth 2.0 Device Flow for the client SDK.
    """

    def login(self, base_url: str, callback: Callable[[str, str], None] | None = None) -> str:
        """
        Initiates the device flow, polls for the token, and stores it in the keyring.
        Returns the access token.

        :param base_url: The base URL of the Coreason API.
        :param callback: Optional callback to handle user code display (verification_uri, user_code).
                         Useful for UI frameworks like Streamlit.
        """
        # 1. Initiate Device Flow
        device_code_url = f"{base_url.rstrip('/')}/auth/device-code"
        try:
            resp = httpx.post(device_code_url)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise RuntimeError(f"Failed to initiate device flow: {e}") from e

        dc_data = DeviceCodeResponse(**resp.json())

        # 2. Display User Code
        if callback:
            callback(dc_data.verification_uri, dc_data.user_code)
        else:
            print(f"\nPlease visit: {dc_data.verification_uri}")
            print(f"And enter code: {dc_data.user_code}\n")

        # 3. Poll for Token
        token_url = f"{base_url.rstrip('/')}/auth/token"
        interval = dc_data.interval
        expires_in = dc_data.expires_in

        # Using Tenacity for polling loop

        poll_state = {"interval": interval}

        def wait_dynamic(retry_state: Any) -> float:
            return poll_state["interval"]

        @retry(
            stop=stop_after_delay(expires_in),
            wait=wait_dynamic,
            retry=retry_if_exception(is_polling_error),
            reraise=True,
        )
        def _poll() -> str:
            try:
                poll_resp = httpx.post(token_url, json={"device_code": dc_data.device_code})

                if poll_resp.status_code == 200:
                    return poll_resp.json()  # Return dict

                if poll_resp.status_code == 400:
                    error_detail = poll_resp.json().get("detail")
                    if error_detail == "authorization_pending":
                        raise AuthorizationPendingError()
                    elif error_detail == "slow_down":
                        poll_state["interval"] += 5
                        raise SlowDownError()
                    elif error_detail == "expired_token":
                        # Don't retry, let it bubble as failure
                        raise RuntimeError("Token expired during polling.")
                    else:
                        raise RuntimeError(f"Authentication failed: {error_detail}")

                poll_resp.raise_for_status()
                # Should not reach here if raise_for_status raises
                raise RuntimeError("Unexpected state")

            except httpx.RequestError as e:
                # Retry on network error?
                # For now treating as pending (retry) or maybe separate logic?
                # Let's treat it as AuthorizationPending (keep trying)
                raise AuthorizationPendingError() from e

        try:
            token_data_dict = _poll()
            token_data = TokenResponse(**token_data_dict)

            # Save to keyring
            keyring.set_password(SERVICE_NAME, USERNAME, token_data.access_token)
            print("Successfully authenticated!")
            return token_data.access_token

        except RetryError:
            raise RuntimeError("Authentication timed out.")
        except Exception as e:
            raise RuntimeError(f"Authentication failed: {e}") from e

    def get_token(self) -> str | None:
        """
        Retrieves the token from keyring if valid.
        Returns None if missing or expired.
        """
        token = keyring.get_password(SERVICE_NAME, USERNAME)
        if not token:
            return None

        # Decode without verification to check expiry
        try:
            # We don't verify signature here because we don't have the public key easily accessible
            # and the server will reject it anyway if invalid.
            jwt.decode(token, options={"verify_signature": False, "verify_exp": True})
        except jwt.ExpiredSignatureError:
            return None
        except jwt.PyJWTError:
            # Malformed or other error
            return None

        # Double check expiration manually just in case
        decoded = jwt.decode(token, options={"verify_signature": False})
        exp = decoded.get("exp")
        if exp and time.time() > exp:
            return None

        # Explicitly cast to str because keyring might return Any in some environments, confusing mypy
        return str(token)
