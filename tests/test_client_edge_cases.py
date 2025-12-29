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
import unittest
from unittest.mock import MagicMock, patch

import httpx
import jwt

from coreason_adlc_api.client import CoreasonClient
from coreason_adlc_api.client_auth import ClientAuthManager
from coreason_adlc_api.exceptions import (
    ClientError,
    CoreasonError,
    ServerError,
)


class TestClientAuthEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        self.auth = ClientAuthManager()
        self.base_url = "http://test-edge"

    @patch("coreason_adlc_api.client_auth.httpx.post")
    def test_login_malformed_json_response(self, mock_post: MagicMock) -> None:
        """Test that malformed JSON from the server raises an error."""
        resp = MagicMock()
        resp.status_code = 200
        # side_effect to raise JSONDecodeError when .json() is called
        resp.json.side_effect = json.JSONDecodeError("Expecting value", "doc", 0)
        resp.raise_for_status = MagicMock()

        mock_post.return_value = resp

        with self.assertRaises(json.JSONDecodeError):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    @patch("coreason_adlc_api.client_auth.keyring.set_password")
    def test_login_keyring_error(self, mock_keyring: MagicMock, mock_post: MagicMock) -> None:
        """Test that keyring failures during save raise an exception."""
        # Setup successful auth flow mocks
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "uc",
            "verification_uri": "uri",
            "expires_in": 300,
            "interval": 1,
        }

        token_resp = MagicMock()
        token_resp.status_code = 200
        token_resp.json.return_value = {"access_token": "tok", "expires_in": 3600}

        mock_post.side_effect = [device_resp, token_resp]

        # Keyring fails
        mock_keyring.side_effect = Exception("Keyring locked")

        with self.assertRaisesRegex(Exception, "Keyring locked"):
            self.auth.login(self.base_url)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    def test_login_callback_exception(self, mock_post: MagicMock) -> None:
        """Test that exceptions in the user callback propagate."""
        device_resp = MagicMock()
        device_resp.json.return_value = {
            "device_code": "dc",
            "user_code": "uc",
            "verification_uri": "uri",
            "expires_in": 300,
            "interval": 1,
        }
        mock_post.return_value = device_resp

        callback = MagicMock(side_effect=ValueError("UI Crash"))

        with self.assertRaisesRegex(ValueError, "UI Crash"):
            self.auth.login(self.base_url, callback=callback)

    @patch("coreason_adlc_api.client_auth.httpx.post")
    def test_login_base_url_handling(self, mock_post: MagicMock) -> None:
        """Test that base_url with trailing slash is handled correctly."""
        # Setup failure immediately to check the URL called
        mock_post.side_effect = httpx.RequestError("Stop here")

        try:
            self.auth.login("http://slash.com/")
        except RuntimeError:
            pass

        # Verify the call stripped the slash
        # call_args[0][0] is the url
        called_url = mock_post.call_args[0][0]
        self.assertEqual(called_url, "http://slash.com/auth/device-code")

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_keyring_error(self, mock_get: MagicMock) -> None:
        """Test that keyring read errors propagate."""
        mock_get.side_effect = Exception("Keyring access denied")
        with self.assertRaisesRegex(Exception, "Keyring access denied"):
            self.auth.get_token()

    @patch("coreason_adlc_api.client_auth.keyring.get_password")
    def test_get_token_missing_exp_claim(self, mock_get: MagicMock) -> None:
        """Test that a valid JWT missing the 'exp' claim is treated as invalid (returns None)."""
        mock_get.return_value = "token_no_exp"

        # jwt.decode raising MissingRequiredClaimError (subclass of PyJWTError)
        with patch("coreason_adlc_api.client_auth.jwt.decode", side_effect=jwt.MissingRequiredClaimError("exp")):
            token = self.auth.get_token()
            self.assertIsNone(token)


class TestCoreasonClientEdgeCases(unittest.TestCase):
    def setUp(self) -> None:
        CoreasonClient._instance = None
        self.client = CoreasonClient("http://test")

        # Patch the underlying httpx client's request method
        self.patcher = patch.object(self.client.client, "request")
        self.mock_request = self.patcher.start()
        self.addCleanup(self.patcher.stop)

    def tearDown(self) -> None:
        if CoreasonClient._instance:
            CoreasonClient._instance.close()
        CoreasonClient._instance = None

    @patch("coreason_adlc_api.client.ClientAuthManager.get_token")
    def test_interceptor_propagates_keyring_error(self, mock_get_token: MagicMock) -> None:
        """Test that if auth fails hard (exception), the request fails hard."""
        mock_get_token.side_effect = Exception("Critical Auth Fail")

        req = httpx.Request("GET", "http://test/api")

        with self.assertRaisesRegex(Exception, "Critical Auth Fail"):
            self.client._inject_auth_header(req)

    def test_empty_error_body(self) -> None:
        """Test handling of 400 Bad Request with empty body."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.is_success = False
        resp.json.side_effect = json.JSONDecodeError("Expecting value", "", 0)
        resp.text = ""
        resp.reason_phrase = "Bad Request"
        self.mock_request.return_value = resp

        with self.assertRaises(ClientError) as cm:
            self.client.request("GET", "/test")
        self.assertEqual(cm.exception.message, "Bad Request")

    def test_malformed_json_error_body(self) -> None:
        """Test handling of error response with malformed JSON."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.is_success = False
        resp.json.side_effect = json.JSONDecodeError("Expecting value", "{invalid", 0)
        resp.text = "{invalid"
        self.mock_request.return_value = resp

        with self.assertRaises(ClientError) as cm:
            self.client.request("GET", "/test")
        self.assertEqual(cm.exception.message, "{invalid")

    def test_ambiguous_json_error(self) -> None:
        """Test handling of JSON error response without standard keys."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 400
        resp.is_success = False
        resp.json.return_value = {"info": "Something went wrong", "code": 123}
        resp.text = '{"info": "Something went wrong", "code": 123}'
        self.mock_request.return_value = resp

        # Should fallback to text representation
        with self.assertRaises(ClientError) as cm:
            self.client.request("GET", "/test")
        self.assertEqual(cm.exception.message, '{"info": "Something went wrong", "code": 123}')

    def test_header_access_in_exception(self) -> None:
        """Verify that headers are accessible in the caught exception."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 429
        resp.is_success = False
        resp.json.return_value = {"message": "Too many requests"}
        resp.headers = httpx.Headers({"X-RateLimit-Reset": "60"})
        self.mock_request.return_value = resp

        try:
            self.client.request("GET", "/test")
        except CoreasonError as e:
            self.assertIsNotNone(e.response)
            if e.response:  # guard for mypy
                self.assertEqual(e.response.headers["X-RateLimit-Reset"], "60")

    def test_status_boundary_499(self) -> None:
        """Test handling of status code 499 (Client Closed Request)."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 499
        resp.is_success = False
        resp.json.return_value = {"detail": "Client Closed"}
        self.mock_request.return_value = resp

        with self.assertRaises(ClientError):
            self.client.request("GET", "/test")

    def test_status_boundary_599(self) -> None:
        """Test handling of status code 599 (Network Connect Timeout Error)."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 599
        resp.is_success = False
        resp.json.return_value = {"detail": "Timeout"}
        self.mock_request.return_value = resp

        with self.assertRaises(ServerError):
            self.client.request("GET", "/test")

    def test_status_boundary_399(self) -> None:
        """Test handling of status code 399 (Unassigned) if treated as error."""
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 399
        resp.is_success = False
        resp.json.return_value = {"detail": "Weird 3xx Error"}
        self.mock_request.return_value = resp

        # Fallback to CoreasonError as it's not 4xx or 5xx
        with self.assertRaises(CoreasonError) as cm:
            self.client.request("GET", "/test")
        self.assertNotIsInstance(cm.exception, ClientError)
        self.assertNotIsInstance(cm.exception, ServerError)

    def test_redirect_handling(self) -> None:
        """Test handling of 302 Redirect (success path)."""
        # Note: In our client implementation, if is_success is False (which it is for 302),
        # it falls through to exceptions. But 302 is not mapped, so it raises CoreasonError.
        # This test documents that behavior.
        resp = MagicMock(spec=httpx.Response)
        resp.status_code = 302
        resp.is_success = False  # httpx defaults to False for 302
        resp.json.side_effect = json.JSONDecodeError("Expect", "", 0)
        resp.text = "Found"
        self.mock_request.return_value = resp

        with self.assertRaises(CoreasonError):
            self.client.request("GET", "/redirect")
