# Copyright (c) 2025 CoReason, Inc.
#
# This software is proprietary and dual-licensed.
# Licensed under the Prosperity Public License 3.0 (the "License").
# A copy of the license is available at https://prosperitylicense.com/versions/3.0.0
# For details, see the LICENSE file.
# Commercial use beyond a 30-day trial requires a separate license.
#
# Source Code: https://github.com/CoReason-AI/coreason_adlc_api

from loguru import logger
from presidio_analyzer import AnalyzerEngine


class PIIAnalyzer:
    """
    Singleton wrapper for Microsoft Presidio Analyzer to ensure the model is loaded only once.
    """

    _instance = None
    _analyzer: AnalyzerEngine | None = None

    def __new__(cls) -> "PIIAnalyzer":
        if cls._instance is None:
            cls._instance = super(PIIAnalyzer, cls).__new__(cls)
        return cls._instance

    def get_analyzer(self) -> AnalyzerEngine:
        if self._analyzer is None:
            logger.info("Initializing Presidio Analyzer Engine...")
            # We use the default configuration which loads the "en_core_web_lg" model if available,
            # or falls back to "en_core_web_sm".
            # Requirement says: "en_core_web_lg" is selected.
            # We should probably configure it explicitly if needed, but default usually works if model is installed.

            # Note: In a real prod env with strict requirements, we might define the configuration explicitly.
            # configuration = {
            #     "nlp_engine_name": "spacy",
            #     "models": [{"lang_code": "en", "model_name": "en_core_web_lg"}],
            # }
            # provider = NlpEngineProvider(nlp_configuration=configuration)
            # nlp_engine = provider.create_engine()
            # self._analyzer = AnalyzerEngine(nlp_engine=nlp_engine, supported_languages=["en"])

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

        # Analyze
        results = analyzer.analyze(
            text=text_payload, entities=["PHONE_NUMBER", "EMAIL_ADDRESS", "PERSON"], language="en"
        )

        # Replace
        # Presidio has an Anonymizer engine too, but the requirement specifically says:
        # "Replace detected entities... with <REDACTED>."
        # Actually it says "Replace detected entities (PHONE, PERSON, EMAIL) with <REDACTED>."
        # And in the table: "Replace findings with <REDACTED {ENTITY_TYPE}>."
        # I will follow the table: <REDACTED {ENTITY_TYPE}>.

        # We process results in reverse order to preserve indices
        sorted_results = sorted(results, key=lambda x: x.start, reverse=True)

        scrubbed_text = list(text_payload)

        for result in sorted_results:
            start = result.start
            end = result.end
            entity_type = result.entity_type

            # Map Presidio types to requested types if needed, or just use Presidio types.
            # Presidio uses: PHONE_NUMBER, EMAIL_ADDRESS, PERSON
            # Table says: PHONE, EMAIL, PERSON
            # I'll normalize for cleanliness if preferred, or just use raw.
            # "with <REDACTED {ENTITY_TYPE}>" -> <REDACTED PERSON>, <REDACTED PHONE_NUMBER>

            replacement = f"<REDACTED {entity_type}>"
            scrubbed_text[start:end] = replacement

        return "".join(scrubbed_text)

    except Exception as e:
        logger.error(f"PII Scrubbing failed: {e}")
        # Fail safe?
        # If scrubbing fails, should we block or pass?
        # BG-02: "Eliminate legal liability... Zero PII detected".
        # If we return raw text, we risk leaking PII.
        # But blocking disrupts service.
        # Given "Strict Governance", blocking or returning a generic error is safer than leaking.
        # However, for this implementation, I will catch and return a placeholder error string to the caller
        # so they know something went wrong, rather than leaking the original.
        raise ValueError("PII Scrubbing failed.") from e
