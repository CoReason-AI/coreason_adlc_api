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
    def tearDown(self) -> None:
        if CoreasonClient._instance:
            CoreasonClient._instance.close()
        CoreasonClient._instance = None

    @patch("coreason_adlc_api.client.ClientAuthManager.get_token")
    def test_interceptor_propagates_keyring_error(self, mock_get_token: MagicMock) -> None:
        """Test that if auth fails hard (exception), the request fails hard."""
        mock_get_token.side_effect = Exception("Critical Auth Fail")

        client = CoreasonClient("http://test")
        req = httpx.Request("GET", "http://test/api")

        with self.assertRaisesRegex(Exception, "Critical Auth Fail"):
            client._inject_auth_header(req)
