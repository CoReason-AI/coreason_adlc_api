# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine

try:
    from presidio_analyzer import AnalyzerEngine
except ImportError:
    AnalyzerEngine = None  # type: ignore[assignment,misc,unused-ignore]


class PIIAnalyzer:
    """
    Singleton wrapper for Microsoft Presidio Analyzer to ensure the model is loaded only once.
    """

    _instance = None
    _analyzer: Optional["AnalyzerEngine"] = None

    def __new__(cls) -> "PIIAnalyzer":
        if cls._instance is None:
            cls._instance = super(PIIAnalyzer, cls).__new__(cls)
        return cls._instance

    def get_analyzer(self) -> Optional["AnalyzerEngine"]:
        if self._analyzer is None:
            if AnalyzerEngine is None:
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
    Supported types: dict, list, tuple, str.
    """
    if isinstance(data, str):
        return scrub_pii_payload(data)
    if not isinstance(data, (dict, list, tuple)):
        return data

    # Iterative stack-based approach to avoid RecursionError
    # We use a stack to traverse and build the structure.
    # Handling tuples is tricky because they are immutable.
    # We can convert tuples to lists, process them, and convert back.
    # Or, given this is an iterative modifier, we might need a different approach if we want to preserve exact
    # types perfectly deep down without recursion.
    # However, standard JSON payloads usually become lists.
    # If the input is a python object with tuples, we can convert them to lists for the result.
    # The requirement is to SCRUB PII. Converting tuple to list is usually acceptable in API contexts.
    # If strict type preservation of tuples is required, it's harder iteratively without bottom-up reconstruction.
    # But let's assume converting tuple -> list is fine (safer for scrubbing).

    # If the root is a tuple, we convert to list first.
    root_is_tuple = isinstance(data, tuple)

    new_data: Any
    if isinstance(data, dict):
        new_data = data.copy()
    elif isinstance(data, tuple):
        new_data = list(data)
    else:  # data is list
        new_data = data[:]

    # Stack contains (target_container, source_container)
    # source_container is the original data
    # target_container is the mutable copy we are building (dict or list)
    stack = [(new_data, data)]

    while stack:
        target, source = stack.pop()

        iterator: Any
        if isinstance(source, dict):
            iterator = source.items()
        elif isinstance(source, (list, tuple)):
            iterator = enumerate(source)
        else:
            continue  # pragma: no cover

        for k, v in iterator:
            if isinstance(v, str):
                # Scrub string
                target[k] = scrub_pii_payload(v)
            elif isinstance(v, (dict, list, tuple)):
                # Create new container
                new_sub: Any
                if isinstance(v, dict):
                    new_sub = v.copy()
                elif isinstance(v, tuple):
                    new_sub = list(v)
                else:
                    new_sub = v[:]

                target[k] = new_sub
                stack.append((new_sub, v))
            else:
                target[k] = v

    if root_is_tuple:
        return tuple(new_data)

    return new_data
