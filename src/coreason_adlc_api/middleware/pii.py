# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from threading import Lock
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine

try:
    from presidio_analyzer import AnalyzerEngine
    _PRESIDIO_AVAILABLE = True
except ImportError:
    _PRESIDIO_AVAILABLE = False


class PIIAnalyzer:
    """
    Singleton wrapper for Microsoft Presidio Analyzer to ensure the model is loaded only once.
    """

    _instance: Optional["PIIAnalyzer"] = None
    _lock: Lock = Lock()
    _analyzer: Optional["AnalyzerEngine"] = None

    def __new__(cls) -> "PIIAnalyzer":
        if not cls._instance:
            with cls._lock:
                if not cls._instance:
                    cls._instance = super(PIIAnalyzer, cls).__new__(cls)
        return cls._instance

    def get_analyzer(self) -> Optional["AnalyzerEngine"]:
        if self._analyzer is None:
            with self._lock:
                if self._analyzer is None:
                    if not _PRESIDIO_AVAILABLE:
                        logger.warning("Presidio Analyzer not available (missing dependency). PII scrubbing will be disabled.")
                        return None

                    logger.info("Initializing Presidio Analyzer Engine...")
                    self._analyzer = AnalyzerEngine()
                    logger.info("Presidio Analyzer Initialized.")
        return self._analyzer


def scrub_pii_payload(text_payload: str | None) -> str | None:
    """
    Scans the payload for PII entities (PHONE, EMAIL, PERSON) and replaces them with <REDACTED {ENTITY_TYPE}>.
    Does NOT log the original text.
    """
    if not text_payload:
        return text_payload

    try:
        analyzer = PIIAnalyzer().get_analyzer()
        if analyzer is None:
            # Fallback for when library is missing (e.g. Python 3.14)
            # Failing closed is safest for a security tool, but failing open allows the app to run.
            # Given the context, if the library is missing, we likely can't scrub.
            # Returning a placeholder indicating failure.
            return "<REDACTED: PII ANALYZER MISSING>"

        # Analyze
        results = analyzer.analyze(
            text=text_payload, entities=["PHONE_NUMBER", "EMAIL_ADDRESS", "PERSON"], language="en"
        )

        # Replace
        # We process results in reverse order to preserve indices
        sorted_results = sorted(results, key=lambda x: x.start, reverse=True)

        scrubbed_text = list(text_payload)

        for result in sorted_results:
            start = result.start
            end = result.end
            entity_type = result.entity_type

            replacement = f"<REDACTED {entity_type}>"
            scrubbed_text[start:end] = replacement

        return "".join(scrubbed_text)

    except ValueError as e:
        # Spacy raises ValueError for text > 1,000,000 chars
        if "exceeds maximum" in str(e):
            logger.warning(f"PII Scrubbing skipped due to excessive length: {len(text_payload)} chars.")
            return "<REDACTED: PAYLOAD TOO LARGE FOR PII ANALYSIS>"
        logger.error(f"PII Scrubbing failed: {e}")
        raise ValueError("PII Scrubbing failed.") from e
    except Exception as e:
        logger.error(f"PII Scrubbing failed: {e}")
        raise ValueError("PII Scrubbing failed.") from e


def scrub_pii_recursive(data: Any) -> Any:
    """
    Recursively scans and scrubs PII from the input data structure.
    Supported types: dict, list, str.
    """
    if isinstance(data, dict):
        return {k: scrub_pii_recursive(v) for k, v in data.items()}
    elif isinstance(data, list):
        return [scrub_pii_recursive(item) for item in data]
    elif isinstance(data, str):
        return scrub_pii_payload(data)
    else:
        return data
