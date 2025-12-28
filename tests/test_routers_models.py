# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import unittest
from unittest.mock import MagicMock

from coreason_adlc_api.app import app
from coreason_adlc_api.auth.identity import parse_and_validate_token
from fastapi.testclient import TestClient


class TestModelsRouter(unittest.TestCase):
    def setUp(self) -> None:
        self.client = TestClient(app)
        # Clear any existing overrides
        app.dependency_overrides = {}

    def tearDown(self) -> None:
        app.dependency_overrides = {}

    def test_get_model_schema_default(self) -> None:
        """Test retrieving the default schema (e.g., for GPT-4)."""
        # Override auth to succeed
        app.dependency_overrides[parse_and_validate_token] = lambda: MagicMock()

        response = self.client.get("/api/v1/models/gpt-4/schema")
        self.assertEqual(response.status_code, 200)

        schema = response.json()
        self.assertEqual(schema.get("title"), "Configuration for gpt-4")
        self.assertIn("temperature", schema["properties"])
        self.assertIn("top_p", schema["properties"])
        self.assertNotIn("reasoning_effort", schema["properties"])
        self.assertEqual(schema["required"], ["temperature", "top_p"])

    def test_get_model_schema_deepseek(self) -> None:
        """Test retrieving the schema for DeepSeek (Reasoning) models."""
        app.dependency_overrides[parse_and_validate_token] = lambda: MagicMock()

        response = self.client.get("/api/v1/models/deepseek-r1/schema")
        self.assertEqual(response.status_code, 200)

        schema = response.json()
        self.assertEqual(schema.get("title"), "Configuration for deepseek-r1")
        self.assertIn("reasoning_effort", schema["properties"])
        self.assertNotIn("temperature", schema["properties"])
        self.assertEqual(schema["required"], ["reasoning_effort"])
        # Validate Enum
        self.assertEqual(schema["properties"]["reasoning_effort"]["enum"], ["low", "medium", "high"])

    def test_get_model_schema_reasoning(self) -> None:
        """Test retrieving the schema for generic reasoning models."""
        app.dependency_overrides[parse_and_validate_token] = lambda: MagicMock()

        response = self.client.get("/api/v1/models/my-reasoning-model/schema")
        self.assertEqual(response.status_code, 200)

        schema = response.json()
        self.assertIn("reasoning_effort", schema["properties"])
        self.assertNotIn("temperature", schema["properties"])

    def test_get_model_schema_unauthorized_missing_header(self) -> None:
        """Test that missing authorization header returns 422 (FastAPI default)."""
        # No override
        response = self.client.get("/api/v1/models/gpt-4/schema")
        self.assertEqual(response.status_code, 422)

    def test_get_model_schema_unauthorized_invalid_header(self) -> None:
        """Test that invalid authorization header returns 401."""
        # No override, real dependency runs
        # We need to rely on the fact that `parse_and_validate_token` raises 401
        # if the header format is wrong or token is bad.

        # Note: TestClient calls the app directly. `parse_and_validate_token`
        # checks `Authorization` header.

        response = self.client.get("/api/v1/models/gpt-4/schema", headers={"Authorization": "Bearer invalid_token"})
        self.assertEqual(response.status_code, 401)
