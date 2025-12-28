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


def test_pii_import_error_coverage() -> None:
    """
    Test the ImportError block by forcing a reload of the module while presidio_analyzer is masked.
    """
    # We need to remove presidio_analyzer from sys.modules temporarily to force re-import
    # and make it fail.

    # Store original module
    original_module = sys.modules.get("presidio_analyzer")

    try:
        # Mock sys.modules to raise ImportError for presidio_analyzer
        with patch.dict(sys.modules):
            sys.modules["presidio_analyzer"] = None # type: ignore
            # If we set it to None, import might raise ModuleNotFoundError or ImportError depending on python version
            # Actually, setting to None usually means "not found" in sys.modules, so import logic proceeds to find it.
            # To FORCE failure, we need to make sure the loader fails.

            # Better strategy: Patch builtins.__import__? Too risky.

            # If I set it to None in sys.modules, Python 3.x treats it as "module not found" cache?
            # No, if it is in sys.modules as None, import raises ImportError.

            # Let's try reloading pii module.
            # We must be careful not to break other tests.

            # We need to unimport pii first?
            if "coreason_adlc_api.middleware.pii" in sys.modules:
                del sys.modules["coreason_adlc_api.middleware.pii"]

            # Now import it again
            # We need to simulate ImportError when it tries `from presidio_analyzer import AnalyzerEngine`

            # Side effect of import is hard to mock if we don't control the environment.
            # But if sys.modules['presidio_analyzer'] is None, 'import presidio_analyzer' raises ImportError?
            # Let's verify this behavior.

            # Actually, `sys.modules['name'] = None` is an optimization to prevent import.
            # It raises ModuleNotFoundError.

            # So:
            sys.modules["presidio_analyzer"] = None # type: ignore

            # Now import pii
            import coreason_adlc_api.middleware.pii as pii_module
            reload(pii_module)

            assert pii_module.AnalyzerEngine is None

    except Exception:
        # If anything fails, ensure we don't break the world.
        raise
    finally:
        # Restore
        if original_module:
            sys.modules["presidio_analyzer"] = original_module
        else:
            sys.modules.pop("presidio_analyzer", None)

        # Reload pii correctly to restore state for other tests
        if "coreason_adlc_api.middleware.pii" in sys.modules:
             reload(sys.modules["coreason_adlc_api.middleware.pii"])
