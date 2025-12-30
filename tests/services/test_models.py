# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import pytest

from coreason_adlc_api.services.models import ModelService


class TestModelService:
    @pytest.fixture
    def service(self) -> ModelService:
        return ModelService()

    @pytest.mark.asyncio
    async def test_get_model_schema_deepseek(self, service: ModelService) -> None:
        """Test retrieving the schema for DeepSeek models."""
        schema = await service.get_model_schema("deepseek-r1")

        assert schema.get("title") == "Configuration for deepseek-r1"
        assert "reasoning_effort" in schema["properties"]
        assert "temperature" not in schema["properties"]
        assert schema["required"] == ["reasoning_effort"]
        assert schema["properties"]["reasoning_effort"]["enum"] == [
            "low",
            "medium",
            "high",
        ]

    @pytest.mark.asyncio
    async def test_get_model_schema_reasoning(self, service: ModelService) -> None:
        """Test retrieving the schema for other reasoning models."""
        schema = await service.get_model_schema("my-reasoning-model")

        assert "reasoning_effort" in schema["properties"]
        assert "temperature" not in schema["properties"]

    @pytest.mark.asyncio
    async def test_get_model_schema_default(self, service: ModelService) -> None:
        """Test retrieving the schema for standard models (e.g. GPT-4)."""
        schema = await service.get_model_schema("gpt-4")

        assert schema.get("title") == "Configuration for gpt-4"
        assert "temperature" in schema["properties"]
        assert "top_p" in schema["properties"]
        assert "reasoning_effort" not in schema["properties"]
        assert schema["required"] == ["temperature", "top_p"]
        assert schema["properties"]["temperature"]["default"] == 0.7
        assert schema["properties"]["top_p"]["default"] == 1.0

    @pytest.mark.asyncio
    async def test_get_model_schema_case_insensitive(self, service: ModelService) -> None:
        """Test that model ID matching is case insensitive."""
        schema = await service.get_model_schema("DEEPSEEK-R1")
        assert "reasoning_effort" in schema["properties"]

        schema = await service.get_model_schema("GPT-4")
        assert "temperature" in schema["properties"]
