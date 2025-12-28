# Coreason ADLC API

Welcome to the **Coreason ADLC API** documentation.

This middleware provides a secure, GxP-compliant layer for AI development in biopharmaceutical environments. It enforces PII scrubbing, budget caps, and strict governance policies (ADLC) to prevent "Toxic Telemetry" and ensure auditability.

## Key Features

*   **PII Scrubbing**: In-memory scrubbing of sensitive data using Presidio and Spacy before it hits the logs.
*   **Budget Guardrails**: Atomic, daily budget enforcement per user to prevent run-away costs.
*   **Audit Trails**: Immutable execution records stored in PostgreSQL.
*   **RBAC**: Role-Based Access Control integrated with your Identity Provider.
*   **Vault**: Secure storage for API keys, decrypted only in memory during inference.

## Quick Links

*   [Getting Started](getting_started.md): Installation and setup guide.
*   [Architecture](architecture.md): Understand the design philosophy and components.
*   [API Reference](api/auth.md): Detailed endpoint documentation.
*   [Contributing](guides/contributing.md): For developers working on the API itself.
