# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

import asyncio
from typing import TYPE_CHECKING, Any, Optional

from loguru import logger

if TYPE_CHECKING:
    from presidio_analyzer import AnalyzerEngine

try:
    from presidio_analyzer import AnalyzerEngine
except Exception as e:
    # Catching Exception because presidio-analyzer/spacy can raise
    # pydantic.v1.errors.ConfigError (RuntimeError) on Python 3.14
    logger.warning(f"Failed to import presidio_analyzer: {e}")
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

    def init_analyzer(self) -> None:
        """
        Explicitly initialize the analyzer. Useful for warm-up during startup.
        """
        if self._analyzer is None:
            if AnalyzerEngine is None:
                logger.warning("Presidio Analyzer not available (missing dependency). PII scrubbing will be disabled.")
                return

            logger.info("Initializing Presidio Analyzer Engine...")
            self._analyzer = AnalyzerEngine()
            logger.info("Presidio Analyzer Initialized.")

    def get_analyzer(self) -> Optional["AnalyzerEngine"]:
        if self._analyzer is None:
            self.init_analyzer()
        return self._analyzer


async def scrub_pii_payload(text_payload: str | None) -> str | None:
    """
    Scans the payload for PII entities (PHONE, EMAIL, PERSON) and replaces them with <REDACTED {ENTITY_TYPE}>.
    Does NOT log the original text.
    Runs in a thread executor to avoid blocking the event loop.
    """
    if not text_payload:
        return text_payload

    loop = asyncio.get_running_loop()

    try:
        # We run the blocking analysis in a thread executor
        return await loop.run_in_executor(None, _scrub_sync, text_payload)
    except Exception as e:
        logger.error(f"PII Scrubbing failed: {e}")
        raise ValueError("PII Scrubbing failed.") from e


def _scrub_sync(text_payload: str) -> str:
    """
    Synchronous implementation of scrubbing logic to be run in executor.
    """
    try:
        analyzer = PIIAnalyzer().get_analyzer()
        if analyzer is None:
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
        raise e


async def scrub_pii_recursive(data: Any) -> Any:
    """
    Recursively (iteratively) scans and scrubs PII from the input data structure.
    Supported types: dict, list, tuple, str.
    Returns: A new structure with PII redacted. Tuples are converted to lists.
    """
    if isinstance(data, str):
        return await scrub_pii_payload(data)
    if not isinstance(data, (dict, list, tuple)):
        return data

    # Iterative stack-based approach to avoid RecursionError

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
                # Scrub string (async)
                target[k] = await scrub_pii_payload(v)
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
