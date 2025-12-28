# Security Architecture

The Coreason ADLC API is designed as a **"Clean Room"** environment. It assumes that the developer's laptop is untrusted and the cloud model providers are external entities. The middleware acts as the secure bridge.

## 1. Vault Architecture (Secrets Management)

We do not trust the client (Developer's Machine) with API keys.

### Encryption at Rest
All API keys (e.g., OpenAI, DeepSeek keys) are stored in the `vault.secrets` table using **AES-256-GCM** encryption.

*   **Key Source**: `ENCRYPTION_KEY` environment variable (32-byte hex).
*   **IV (Initialization Vector)**: A unique random IV is generated for every record.
*   **Storage Format**: `Base64( IV + Ciphertext )`.

### Decryption Flow
1.  **Request**: User requests an inference task (e.g., "Run this prompt").
2.  **Lookup**: The API identifies the required model provider.
3.  **Decryption**: The `vault.crypto` module decrypts the API key **in memory**.
4.  **Usage**: The key is passed to `litellm` for the duration of the request.
5.  **Disposal**: The key is scoped to the request function and is garbage collected immediately after. It is never logged or returned to the client.

## 2. PII Scrubbing (The Sentinel)

To prevent data leaks ("Toxic Telemetry"), we implement a "scrub-first" policy for logging.

*   **Engine**: Microsoft Presidio (wrapping Spacy `en_core_web_lg`).
*   **Placement**: The scrubber sits in the `interceptor` layer. It sees the raw data *after* it leaves the user but *before* it hits the database.
*   **Scope**:
    *   **Inbound**: Prompts are scrubbed before being logged to `telemetry_logs`. (Note: The *Raw* prompt is sent to the LLM for inference, but the *Logged* version is sanitized).
    *   **Outbound**: Model responses are scrubbed before logging.

**Limitation**: PII detection is probabilistic. While high-accuracy models are used, 100% detection cannot be guaranteed. This is a mitigation control, not a complete elimination of risk.

## 3. Threat Model & Boundaries

| Boundary | Trust Level | Controls |
| :--- | :--- | :--- |
| **Developer Laptop** | **Low (Untrusted)** | TLS 1.3 only. No direct DB access. No raw API keys. |
| **Coreason Middleware** | **High (Trusted)** | RBAC, Budget enforcement, PII scrubbing. |
| **Database (Postgres)** | **High (Trusted)** | Private Subnet. Encrypted storage. |
| **LLM Provider (Cloud)** | **Medium (External)** | Contractual agreements. Data sent is raw (necessary for function) but logs are scrubbed locally. |

## 4. Network Security

*   **TLS 1.3**: All communication between Client and Middleware must be encrypted.
*   **Air Gap Friendly**: The container can run without outbound internet *if* local LLMs are used (e.g., vLLM) and pointed to by the `litellm` config.
*   **No Inbound Access**: The Middleware does not require inbound connections from the internet, only from the internal corporate network (or localhost).
