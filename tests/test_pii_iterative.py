from coreason_adlc_api.middleware.pii import scrub_pii_recursive
import pytest

def test_deep_recursion_iterative():
    """
    Ensures that the new iterative implementation handles deep structures without RecursionError.
    """
    depth = 2000
    deep_structure = "leaf"
    for _ in range(depth):
        deep_structure = {"k": deep_structure}

    result = scrub_pii_recursive(deep_structure)

    current = result
    for _ in range(depth):
        assert "k" in current
        current = current["k"]
    assert current == "leaf"

def test_scrub_pii_iterative_branches():
    """
    Tests various branches of the iterative scrub_pii_recursive function to ensure 100% coverage.
    """
    # 1. Non-container type (int)
    assert scrub_pii_recursive(123) == 123

    # 2. List input
    input_list = ["hello", 123, {"key": "world"}]
    # mocking scrub_pii_payload implicitely by expectation (assuming it returns same string if no PII)
    result_list = scrub_pii_recursive(input_list)
    assert result_list == ["hello", 123, {"key": "world"}]
    assert result_list is not input_list # Should be a copy

    # 3. Nested list in dict
    input_nested = {"a": [1, "test"]}
    result_nested = scrub_pii_recursive(input_nested)
    assert result_nested == {"a": [1, "test"]}

    # 4. Mixed types in list/dict
    input_mixed = [1, 2.5, True, None]
    assert scrub_pii_recursive(input_mixed) == input_mixed

    # 5. Top-level string
    assert scrub_pii_recursive("hello world") == "hello world"
