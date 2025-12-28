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
import time
import unittest
from unittest.mock import MagicMock, patch

import httpx
import jwt
from coreason_adlc_api.client import CoreasonClient
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


class TestClientAuthManager(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = ClientAuthManager()
        self.base_url = "http://test-api"
        # Reset any global patches if needed, though patching in methods is safer

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.keyring.set_password")
    @patch("coreason_adlc_api.client_auth.print")
    def test_login_success(self, mock_print: MagicMock, mock_keyring: MagicMock, mock_post: MagicMock) -> None:
        # Mock device code response
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc_123",
            "user_code": "USER-123",
            "verification_uri": "http://verify",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        # Mock token response (success)
        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "access_token": "token_123",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        # Sequence: Device Code -> Token Success
        mock_post.side_effect = [device_resp, token_resp]

        token = self.auth.login(self.base_url)

        self.assertEqual(token, "token_123")
        mock_keyring.assert_called_with("coreason-adlc-api-key", "default_user", "token_123")
        self.assertEqual(mock_post.call_count, 2)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.keyring.set_password")
    def test_login_with_callback(self, mock_keyring: MagicMock, mock_post: MagicMock) -> None:
        # Mock responses
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc_999",
            "user_code": "USER-999",
            "verification_uri": "http://verify-me",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {
            "access_token": "token_callback",
            "token_type": "Bearer",
            "expires_in": 3600,
        }

        mock_post.side_effect = [device_resp, token_resp]

        callback = MagicMock()
        self.auth.login(self.base_url, callback=callback)

        callback.assert_called_once_with("http://verify-me", "USER-999")

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.keyring.set_password")
    @patch("coreason_adlc_api.client_auth.time.sleep")  # Speed up test
    def test_login_flow_wait_and_slow_down(
        self, mock_sleep: MagicMock, mock_keyring: MagicMock, mock_post: MagicMock
    ) -> None:
        # Device Code
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc_123",
            "user_code": "USER-123",
            "verification_uri": "http://verify",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        # Responses:
        # 1. Device Code
        # 2. 400 authorization_pending
        # 3. 400 slow_down
        # 4. 200 Success
        resp_pending = MagicMock()
        resp_pending.status_code = 400
        resp_pending.json.return_value = {"detail": "authorization_pending"}

        resp_slow = MagicMock()
        resp_slow.status_code = 400
        resp_slow.json.return_value = {"detail": "slow_down"}

        resp_success = MagicMock()
        resp_success.status_code = 200
        resp_success.json.return_value = {
            "access_token": "token_final",
            "expires_in": 3600,
        }

        mock_post.side_effect = [device_resp, resp_pending, resp_slow, resp_success]

        token = self.auth.login(self.base_url)
        self.assertEqual(token, "token_final")

        # Verify interval increase on slow_down
        # sleep calls:
        # 1. after pending (interval=1)
        # 2. after slow_down (interval becomes 1+5 = 6)
        # 3. (loop breaks on success)
        # Actually logic is: sleep(interval) is called at end of loop.
        # Loop 1: pending -> sleep(1)
        # Loop 2: slow_down -> interval+=5 -> sleep(6)
        # Loop 3: success -> return
        self.assertEqual(mock_sleep.call_count, 2)
        mock_sleep.assert_any_call(1)
        mock_sleep.assert_any_call(6)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.time.sleep")
    def test_login_expired_token_error(self, mock_sleep: MagicMock, mock_post: MagicMock) -> None:
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc_123",
            "user_code": "u",
            "verification_uri": "v",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        resp_expired = MagicMock()
        resp_expired.status_code = 400
        resp_expired.json.return_value = {"detail": "expired_token"}

        mock_post.side_effect = [device_resp, resp_expired]

        with self.assertRaisesRegex(RuntimeError, "Token expired during polling"):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    def test_login_unknown_400_error(self, mock_post: MagicMock) -> None:
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "u",
            "verification_uri": "v",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        resp_err = MagicMock()
        resp_err.status_code = 400
        resp_err.json.return_value = {"detail": "unknown_reason"}

        mock_post.side_effect = [device_resp, resp_err]

        with self.assertRaisesRegex(RuntimeError, "Authentication failed: unknown_reason"):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    def test_login_500_error(self, mock_post: MagicMock) -> None:
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "u",
            "verification_uri": "v",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        resp_err = MagicMock()
        resp_err.status_code = 500
        resp_err.raise_for_status.side_effect = httpx.HTTPStatusError("500", request=MagicMock(), response=resp_err)

        mock_post.side_effect = [device_resp, resp_err]

        with self.assertRaises(httpx.HTTPStatusError):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.time.time")
    @patch("coreason_adlc_api.client_auth.time.sleep")
    def test_login_timeout(self, mock_sleep: MagicMock, mock_time: MagicMock, mock_post: MagicMock) -> None:
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "u",
            "verification_uri": "v",
            "expires_in": 5,  # Short expiry
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        mock_post.return_value = device_resp  # First call

        # Time sequence: start=0, loop1=1 (ok), loop2=6 (timeout)
        mock_time.side_effect = [0, 1, 6]

        # We need mock_post to handle the token polling too, which won't happen if we time out immediately
        # But here start_time is 0.
        # Loop condition: (now - start) < expires_in
        # 1st check: (1 - 0) < 5 -> True. Enters loop. Polls.
        # 2nd check: (6 - 0) < 5 -> False. Breaks.

        resp_pending = MagicMock()
        resp_pending.status_code = 400
        resp_pending.json.return_value = {"detail": "authorization_pending"}

        mock_post.side_effect = [device_resp, resp_pending]

        with self.assertRaisesRegex(RuntimeError, "Authentication timed out"):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    def test_login_device_code_failure(self, mock_post: MagicMock) -> None:
        mock_post.side_effect = httpx.HTTPError("Network fail")
        with self.assertRaisesRegex(RuntimeError, "Failed to initiate device flow"):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.time.sleep")
    def test_login_poll_network_error(self, mock_sleep: MagicMock, mock_post: MagicMock) -> None:
        # Test that transient network errors during polling don't crash the loop
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "u",
            "verification_uri": "v",
            "expires_in": 300,
            "interval": 1,
        }
        device_resp.raise_for_status = MagicMock()

        # Sequence: Device -> NetworkError -> Success
        success_resp = MagicMock()
        success_resp.status_code = 200
        success_resp.json.return_value = {"access_token": "tok", "expires_in": 3600}

        mock_post.side_effect = [device_resp, httpx.RequestError("Transient"), success_resp]

        # Also need to mock keyring to avoid error on success
        with patch("coreason_adlc_api.client_auth.keyring.set_password"):
            token = self.auth.login(self.base_url)
            self.assertEqual(token, "tok")

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_missing(self, mock_get: MagicMock) -> None:
        mock_get.return_value = None
        self.assertIsNone(self.auth.get_token())

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_valid(self, mock_get: MagicMock) -> None:
        # Create a valid token
        token = jwt.encode({"exp": time.time() + 3600, "sub": "test"}, "secret", algorithm="HS256")
        mock_get.return_value = token

        self.assertEqual(self.auth.get_token(), token)

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_expired_signature(self, mock_get: MagicMock) -> None:
        # Manually create token and mock decode to raise ExpiredSignatureError
        # Note: Since we use verify_signature=False, pyjwt won't raise ExpiredSignatureError automatically
        # unless verify_exp=True is passed AND it checks it.
        # But my code catches ExpiredSignatureError.
        # Let's see how `jwt.decode` behaves with verify_signature=False and verify_exp=True.
        # It DOES check expiration.

        mock_get.return_value = "expired_token_string"
        with patch("coreason_adlc_api.client_auth.jwt.decode", side_effect=jwt.ExpiredSignatureError):
            self.assertIsNone(self.auth.get_token())

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_malformed(self, mock_get: MagicMock) -> None:
        mock_get.return_value = "garbage"
        with patch("coreason_adlc_api.client_auth.jwt.decode", side_effect=jwt.PyJWTError):
            self.assertIsNone(self.auth.get_token())

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_manual_expiry_check(self, mock_get: MagicMock) -> None:
        # Case where decode doesn't raise but claims say expired (e.g. clock skew margin?)
        # Or just to test the manual check block.
        token_str = "token_expired_manually"
        mock_get.return_value = token_str

        # First decode call
        # Second decode call (manual check)

        # We need to ensure jwt.decode returns a dict with 'exp' in the past
        past = time.time() - 100

        # We mock jwt.decode so we don't depend on actual jwt lib behavior for this specific logic path
        with patch("coreason_adlc_api.client_auth.jwt.decode") as mock_decode:
            mock_decode.return_value = {"exp": past}
            self.assertIsNone(self.auth.get_token())


class TestCoreasonClient(unittest.TestCase):
    def setUp(self) -> None:
        # Reset singleton
        CoreasonClient._instance = None
        self.client = CoreasonClient("http://test")

        # Patch the underlying httpx client's request method for testing our wrapper
        self.patcher = patch.object(self.client.client, "request")
        self.mock_request = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self) -> None:
        if CoreasonClient._instance:
            CoreasonClient._instance.close()
        CoreasonClient._instance = None

    def test_singleton(self) -> None:
        # Reset singleton for this test
        CoreasonClient._instance = None
        c1 = CoreasonClient("http://url1")
        c2 = CoreasonClient("http://url2")
        self.assertIs(c1, c2)
        # c2 init returns early, so base_url remains url1
        self.assertEqual(c1.base_url, "http://url1")

    def test_env_var_default(self) -> None:
        # Need to clear instance before test
        CoreasonClient._instance = None
        with patch.dict("os.environ", {"COREASON_API_URL": "http://env-url"}):
            client = CoreasonClient()
            self.assertEqual(client.base_url, "http://env-url")

    def test_set_project(self) -> None:
        self.client.set_project("auc-123")
        self.assertEqual(self.client.client.headers["X-Coreason-Project-ID"], "auc-123")

    @patch("coreason_adlc_api.client.ClientAuthManager.get_token")
    def test_interceptor_injects_token(self, mock_get_token: MagicMock) -> None:
        mock_get_token.return_value = "secret_token"

        # We need to test the hook directly since we're mocking .request
        req = httpx.Request("GET", "http://test/api/resource")
        self.client._inject_auth_header(req)
        self.assertEqual(req.headers["Authorization"], "Bearer secret_token")

    @patch("coreason_adlc_api.client.ClientAuthManager.get_token")
    def test_interceptor_skips_auth_endpoints(self, mock_get_token: MagicMock) -> None:
        mock_get_token.return_value = "secret_token"

        req = httpx.Request("POST", "http://test/auth/token")
        self.client._inject_auth_header(req)
        self.assertNotIn("Authorization", req.headers)

    @patch("coreason_adlc_api.client.ClientAuthManager.get_token")
    def test_interceptor_no_token(self, mock_get_token: MagicMock) -> None:
        mock_get_token.return_value = None

        req = httpx.Request("GET", "http://test/api")
        self.client._inject_auth_header(req)
        self.assertNotIn("Authorization", req.headers)

    def test_request_success(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 200
        resp.is_success = True
        self.mock_request.return_value = resp

        result = self.client.request("GET", "/test")
        self.assertEqual(result, resp)
        self.mock_request.assert_called_with("GET", "/test")

    def test_request_exceptions_401(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 401
        resp.is_success = False
        resp.json.return_value = {"detail": "Unauthorized"}
        self.mock_request.return_value = resp

        with self.assertRaises(AuthenticationError) as cm:
            self.client.request("GET", "/test")
        self.assertEqual(cm.exception.status_code, 401)
        self.assertEqual(cm.exception.message, "Unauthorized")

    def test_request_exceptions_402(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 402
        resp.is_success = False
        resp.json.return_value = {"error": "Budget exceeded"}
        self.mock_request.return_value = resp

        with self.assertRaises(BudgetExceededError) as cm:
            self.client.request("POST", "/test")
        self.assertEqual(cm.exception.message, "Budget exceeded")

    def test_request_exceptions_422(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 422
        resp.is_success = False
        resp.json.return_value = {"detail": "PII detected"}
        self.mock_request.return_value = resp

        with self.assertRaises(ComplianceViolationError):
            self.client.request("PUT", "/test")

    def test_request_exceptions_429(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 429
        resp.is_success = False
        resp.json.return_value = {"message": "Too many requests"}
        self.mock_request.return_value = resp

        with self.assertRaises(RateLimitError):
            self.client.request("GET", "/test")

    def test_request_exceptions_generic_4xx(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 418
        resp.is_success = False
        resp.json.return_value = {"detail": "Teapot"}
        self.mock_request.return_value = resp

        with self.assertRaises(ClientError):
            self.client.request("GET", "/test")

    def test_request_exceptions_503(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 503
        resp.is_success = False
        # Simulate JSON decode error using correct exception
        resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        resp.text = "Service Unavailable"
        self.mock_request.return_value = resp

        with self.assertRaises(ServiceUnavailableError) as cm:
            self.client.request("GET", "/test")
        self.assertEqual(cm.exception.message, "Service Unavailable")

    def test_request_exceptions_generic_5xx(self) -> None:
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 500
        resp.is_success = False
        resp.json.return_value = {}
        resp.text = ""
        resp.reason_phrase = "Internal Server Error"
        self.mock_request.return_value = resp

        with self.assertRaises(ServerError) as cm:
            self.client.request("GET", "/test")
        self.assertEqual(cm.exception.message, "Internal Server Error")

    def test_request_fallback_exception(self) -> None:
        # Case: status code outside mapped range but is_success is False
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 600
        resp.is_success = False
        resp.json.return_value = {"detail": "Weird"}
        self.mock_request.return_value = resp

        with self.assertRaises(CoreasonError):
            self.client.request("GET", "/test")

    def test_convenience_methods(self) -> None:
        # Setup success response
        resp = MagicMock(spec=httpx.Response)
        resp.is_success = True
        self.mock_request.return_value = resp

        self.client.get("/get", params={"q": 1})
        self.mock_request.assert_called_with("GET", "/get", params={"q": 1})

        self.client.post("/post", json={"a": 1})
        self.mock_request.assert_called_with("POST", "/post", json={"a": 1})

        self.client.put("/put", data="data")
        self.mock_request.assert_called_with("PUT", "/put", data="data")

        self.client.delete("/delete")
        self.mock_request.assert_called_with("DELETE", "/delete")
