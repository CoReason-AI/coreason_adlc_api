import sys
from importlib import reload
from unittest.mock import MagicMock, patch

import pytest

from coreason_adlc_api.middleware import pii


def test_pii_missing_dependency_runtime_check() -> None:
    """
    Test that if AnalyzerEngine is None (runtime check), the code behaves correctly.
    This simulates the state where the library was not imported successfully.
    """
    # Patch AnalyzerEngine to None in the module
    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine", None):
        # Reset singleton
        pii.PIIAnalyzer._instance = None
        pii.PIIAnalyzer._analyzer = None

        analyzer = pii.PIIAnalyzer().get_analyzer()
        assert analyzer is None

        # Test scrubbing
        result = pii.scrub_pii_payload("My phone is 555-5555")
        assert result == "<REDACTED: PII ANALYZER MISSING>"


def test_pii_logic_with_mocked_engine() -> None:
    """
    Test the 'happy path' logic (analyzer instantiation and replacement) even if the real library is missing.
    This ensures 100% coverage of the code lines that would otherwise be unreachable on Python 3.14.
    """
    # Create a mock for AnalyzerEngine class
    mock_engine_cls = MagicMock()
    mock_instance = mock_engine_cls.return_value

    # Mock analysis results
    result_mock = MagicMock()
    result_mock.entity_type = "PHONE_NUMBER"
    result_mock.start = 0
    result_mock.end = 12
    result_mock.score = 1.0

    mock_instance.analyze.return_value = [result_mock]

    # Patch AnalyzerEngine in the module with our mock class
    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine", mock_engine_cls):
        # Reset singleton
        pii.PIIAnalyzer._instance = None
        pii.PIIAnalyzer._analyzer = None

        analyzer = pii.PIIAnalyzer().get_analyzer()
        assert analyzer is not None
        assert analyzer == mock_instance

        # Test scrubbing logic
        text = "555-555-5555"
        result = pii.scrub_pii_payload(text)
        assert result == "<REDACTED PHONE_NUMBER>"


def test_pii_logic_exception_handling_with_mocked_engine() -> None:
    """
    Test exception handling logic using mocks to ensure coverage on Python 3.14.
    """
    mock_engine_cls = MagicMock()
    mock_instance = mock_engine_cls.return_value

    # 1. Test ValueError (Size limit)
    mock_instance.analyze.side_effect = ValueError("exceeds maximum text length")

    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine", mock_engine_cls):
        pii.PIIAnalyzer._instance = None
        pii.PIIAnalyzer._analyzer = None

        result = pii.scrub_pii_payload("Huge text")
        assert result == "<REDACTED: PAYLOAD TOO LARGE FOR PII ANALYSIS>"

    # 2. Test Generic ValueError (e.g. invalid config)
    # This covers the "except ValueError" block fallthrough
    mock_instance.analyze.side_effect = ValueError("Invalid configuration")

    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine", mock_engine_cls):
        pii.PIIAnalyzer._instance = None
        pii.PIIAnalyzer._analyzer = None

        with pytest.raises(ValueError, match="PII Scrubbing failed"):
            pii.scrub_pii_payload("Bad Config")

    # 3. Test Generic Exception
    mock_instance.analyze.side_effect = Exception("Boom")

    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine", mock_engine_cls):
        pii.PIIAnalyzer._instance = None
        pii.PIIAnalyzer._analyzer = None

        with pytest.raises(ValueError, match="PII Scrubbing failed"):
            pii.scrub_pii_payload("Normal text")


def test_pii_empty_payload() -> None:
    """
    Test empty payload short-circuit.
    """
    assert pii.scrub_pii_payload("") == ""
    assert pii.scrub_pii_payload(None) is None


def test_pii_recursion_tuples_missing_deps() -> None:
    """
    Test recursive traversal of tuples even if analyzer is missing.
    Ensures structural logic is covered.
    """
    # Patch AnalyzerEngine to None in the module to simulate missing deps
    with patch("coreason_adlc_api.middleware.pii.AnalyzerEngine", None):
        pii.PIIAnalyzer._instance = None
        pii.PIIAnalyzer._analyzer = None

        data = {"key": ("value", "safe")}
        # Should recurse into dict, then tuple, then strings.
        # Strings should return REDACTED MISSING

        result = pii.scrub_pii_recursive(data)

        assert isinstance(result, dict)
        # Nested tuples are converted to lists for mutability
        assert isinstance(result["key"], list)
        assert result["key"][0] == "<REDACTED: PII ANALYZER MISSING>"
        assert result["key"][1] == "<REDACTED: PII ANALYZER MISSING>"

        # Test Root Tuple Preservation
        tuple_data = ("value",)
        tuple_result = pii.scrub_pii_recursive(tuple_data)
        assert isinstance(tuple_result, tuple)
        assert tuple_result[0] == "<REDACTED: PII ANALYZER MISSING>"


def test_pii_import_error_coverage() -> None:
    """
    Test the ImportError block by forcing a reload of the module while presidio_analyzer is masked.
    """
    original_module = sys.modules.get("presidio_analyzer")

    try:
        with patch.dict(sys.modules):
            sys.modules["presidio_analyzer"] = None  # type: ignore

            # Unload pii module to force re-import logic
            if "coreason_adlc_api.middleware.pii" in sys.modules:
                del sys.modules["coreason_adlc_api.middleware.pii"]

            import coreason_adlc_api.middleware.pii as pii_module

            reload(pii_module)

            assert pii_module.AnalyzerEngine is None  # type: ignore[attr-defined]

    except Exception:
        raise
    finally:
        if original_module:
            sys.modules["presidio_analyzer"] = original_module
        else:
            sys.modules.pop("presidio_analyzer", None)

        if "coreason_adlc_api.middleware.pii" in sys.modules:
            reload(sys.modules["coreason_adlc_api.middleware.pii"])
