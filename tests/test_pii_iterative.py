from typing import Any
from unittest.mock import patch, AsyncMock

import pytest

from coreason_adlc_api.middleware.pii import scrub_pii_recursive


@pytest.mark.asyncio
async def test_deep_recursion_iterative() -> None:
    """
    Ensures that the new iterative implementation handles deep structures without RecursionError.
    """
    depth = 2000
    deep_structure: Any = "leaf"
    for _ in range(depth):
        deep_structure = {"k": deep_structure}

    # Mock the payload scrubber to return identity (awaitable)
    async def identity(x: str | None) -> str | None:
        return x

    with patch("coreason_adlc_api.middleware.pii.scrub_pii_payload", side_effect=identity):
        result = await scrub_pii_recursive(deep_structure)

    current = result
    for _ in range(depth):
        assert "k" in current
        current = current["k"]
    assert current == "leaf"


@pytest.mark.asyncio
async def test_scrub_pii_iterative_branches() -> None:
    """
    Tests various branches of the iterative scrub_pii_recursive function to ensure 100% coverage.
    """
    async def identity(x: str | None) -> str | None:
        return x

    with patch("coreason_adlc_api.middleware.pii.scrub_pii_payload", side_effect=identity):
        # 1. Non-container type (int)
        assert await scrub_pii_recursive(123) == 123

        # 2. List input
        input_list = ["hello", 123, {"key": "world"}]
        result_list = await scrub_pii_recursive(input_list)
        assert result_list == ["hello", 123, {"key": "world"}]
        assert result_list is not input_list  # Should be a copy

        # 3. Nested list in dict
        input_nested = {"a": [1, "test"]}
        result_nested = await scrub_pii_recursive(input_nested)
        assert result_nested == {"a": [1, "test"]}

        # 4. Mixed types in list/dict
        input_mixed = [1, 2.5, True, None]
        assert await scrub_pii_recursive(input_mixed) == input_mixed

        # 5. Top-level string
        assert await scrub_pii_recursive("hello world") == "hello world"
