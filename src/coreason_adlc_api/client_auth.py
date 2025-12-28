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

import httpx
import jwt
import keyring

from typing import Callable

from coreason_adlc_api.auth.schemas import DeviceCodeResponse, TokenResponse

SERVICE_NAME = "coreason-adlc-api-key"
USERNAME = "default_user"


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
        start_time = time.time()

        while (time.time() - start_time) < expires_in:
            try:
                # We send device_code as a JSON body, matching the router expectations
                # The router expects `device_code` string in body.
                # Router signature: async def poll_for_token(device_code: str = Body(..., embed=True))
                # This means JSON body: {"device_code": "..."}
                poll_resp = httpx.post(token_url, json={"device_code": dc_data.device_code})

                if poll_resp.status_code == 200:
                    token_data = TokenResponse(**poll_resp.json())
                    # Save to keyring
                    keyring.set_password(SERVICE_NAME, USERNAME, token_data.access_token)
                    print("Successfully authenticated!")
                    return token_data.access_token

                if poll_resp.status_code == 400:
                    error_detail = poll_resp.json().get("detail")
                    if error_detail == "authorization_pending":
                        pass  # Just wait
                    elif error_detail == "slow_down":
                        interval += 5
                    elif error_detail == "expired_token":
                        raise RuntimeError("Token expired during polling.")
                    else:
                        # Unknown 400 error
                        raise RuntimeError(f"Authentication failed: {error_detail}")
                else:
                    poll_resp.raise_for_status()

            except httpx.RequestError as e:
                # Network error, maybe transient?
                print(f"Network error polling token: {e}")

            time.sleep(interval)

        raise RuntimeError("Authentication timed out.")

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
            # verify_exp=True by default in pyjwt, but requires 'exp' claim.
            # If 'verify_signature' is False, pyjwt still checks 'exp' if verify_exp is not disabled.
            # Wait, pyjwt won't check exp if verify_signature is False unless we explicitly tell it to?
            # Actually, `jwt.decode` with `verify_signature=False` DOES NOT check expiry by default in recent versions?
            # Let's check pyjwt docs or assume standard behavior.
            # Safe bet: decode it, check 'exp' manually or let jwt do it.
            # Actually, if I pass verify_exp=True it might complain if signature is not verified?
            # Let's just decode and check manual timestamp to be robust.
        except jwt.ExpiredSignatureError:
            return None
        except jwt.PyJWTError:
            # Malformed or other error
            return None

        # Double check expiration manually just in case
        # (Though ExpiredSignatureError handles it mostly)
        # Re-decoding to get payload to be safe on manual check
        decoded = jwt.decode(token, options={"verify_signature": False})
        exp = decoded.get("exp")
        if exp and time.time() > exp:
            return None

        # Explicitly cast to str because keyring might return Any in some environments, confusing mypy
        return str(token)
