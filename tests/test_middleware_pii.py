from typing import Any

# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api
from unittest import mock

import pytest
from presidio_analyzer import RecognizerResult

from coreason_adlc_api.middleware.pii import scrub_pii_payload


@pytest.fixture
def mock_analyzer() -> Any:
    # Reset singleton state before test
    from coreason_adlc_api.middleware.pii import PIIAnalyzer

    PIIAnalyzer._instance = None

    with mock.patch("coreason_adlc_api.middleware.pii.AnalyzerEngine") as mock_engine_cls:
        mock_instance = mock.MagicMock()
        mock_engine_cls.return_value = mock_instance
        yield mock_instance

    # Reset after test
    PIIAnalyzer._instance = None


def test_scrub_pii_no_entities(mock_analyzer: Any) -> None:
    """Test scrubbing text with no PII."""
    text = "Hello world, this is a safe message."
    mock_analyzer.analyze.return_value = []

    result = scrub_pii_payload(text)
    assert result == text


def test_scrub_pii_entities_replacement(mock_analyzer: Any) -> None:
    """Test replacement of detected entities."""
    text = "Contact me at 555-0199 or john.doe@example.com."

    # Mock return values from Presidio
    # Indices:
    # 555-0199 starts at 14, ends at 22
    # john.doe@example.com starts at 26, ends at 46

    results = [
        RecognizerResult(entity_type="PHONE_NUMBER", start=14, end=22, score=0.9),
        RecognizerResult(entity_type="EMAIL_ADDRESS", start=26, end=46, score=0.9),
    ]
    mock_analyzer.analyze.return_value = results

    expected = "Contact me at <REDACTED PHONE_NUMBER> or <REDACTED EMAIL_ADDRESS>."
    result = scrub_pii_payload(text)

    assert result == expected


def test_scrub_pii_empty_input(mock_analyzer: Any) -> None:
    """Test empty input returns empty."""
    assert scrub_pii_payload("") == ""
    assert scrub_pii_payload(None) is None


def test_scrub_pii_exception(mock_analyzer: Any) -> None:
    """Test error handling."""
    mock_analyzer.analyze.side_effect = Exception("Analyzer crashed")

    with pytest.raises(ValueError, match="PII Scrubbing failed"):
        scrub_pii_payload("some text")


def test_scrub_pii_generic_value_error(mock_analyzer: Any) -> None:
    """Test handling of ValueError that is NOT length related."""
    mock_analyzer.analyze.side_effect = ValueError("Some internal value error")

    with pytest.raises(ValueError, match="PII Scrubbing failed"):
        scrub_pii_payload("some text")
