# Coreason ADLC API

Secure ADLC Middleware enforcing PII scrubbing, budget caps, and strict governance.

[![CI](https://github.com/CoReason-AI/coreason_adlc_api/actions/workflows/ci.yml/badge.svg)](https://github.com/CoReason-AI/coreason_adlc_api/actions/workflows/ci.yml)

## Overview

In the high-stakes environment of biopharmaceutical development, the **Coreason ADLC API** resolves the tension between rapid AI innovation and GxP compliance. It acts as a server-side "hard gate" that:

*   **Enforces Budget Limits:** Prevents "Cloud Bill Shock" via atomic daily spend caps.
*   **Scrubs PII In-Memory:** Prevents "Toxic Telemetry" by sanitizing data before it touches logs.
*   **Guarantees Identity:** Links every AI insight to a verified human identity via OIDC.

For detailed documentation, please visit our **[Documentation Site](docs/index.md)**.

## Key Features

*   **Asynchronous & Scalable**: Built on FastAPI and Uvicorn.
*   **Universal LLM Proxy**: Uses `litellm` to interface with any provider.
*   **Immutable Audit Logs**: Leveraging PostgreSQL for GxP-compliant record keeping.
*   **Vault Architecture**: In-memory decryption of API keys.

## Quick Links

*   [Getting Started](docs/getting_started.md)
*   [Architecture Philosophy](docs/architecture.md)
*   [Security Architecture](docs/security.md)
*   [Client SDK Guide](docs/guides/client_sdk.md)
*   [API Reference](docs/api/auth.md)

## Installation

```bash
pip install coreason-adlc-api
```

Or for development:

```bash
poetry install
```

## License

This software is proprietary and dual-licensed under the **Prosperity Public License 3.0**.
