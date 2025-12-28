# Architecture

## The Philosophy (The Why)

In the high-stakes environment of biopharmaceutical development, we face a critical tension: the need for rapid AI innovation versus the absolute requirement for GxP compliance, data sovereignty, and auditability. The standard approach—allowing developers direct access to model APIs—creates a "Black Box" liability where costs spiral and decision provenance is lost.

We architected the **coreason_adlc_api** to resolve this by shifting governance from a client-side "honor system" to a server-side "hard gate." Our intent is to prevent "Toxic Telemetry" and "Cloud Bill Shock" while ensuring that every AI-generated insight is inextricably linked to a human identity. This middleware acts as a "Clean Room" airlock, securing the data plane without hindering developer velocity.

## Under the Hood (The Dependencies & Logic)

The architecture leverages a stack chosen for concurrency, security, and integration rather than raw generative capability:

*   **fastapi & uvicorn**: The backbone is asynchronous, designed to handle high-concurrency inference requests without blocking the application logic.
*   **litellm**: This dependency underscores our "Borrow to Build" mandate. Instead of writing custom clients for every model provider, we use litellm as a universal proxy, allowing the middleware to intercept payloads regardless of the underlying model.
*   **presidio-analyzer & spacy**: These libraries provide the "scrubbing" intelligence. By integrating Microsoft’s Presidio directly into the memory stream, we ensure that PII detection happens locally and in-memory, intercepting sensitive data before it ever touches a disk.
*   **redis & asyncpg**: Performance is critical. redis handles high-speed, atomic budget counting, while asyncpg ensures non-blocking writes to the immutable PostgreSQL audit logs.
*   **cryptography**: Security is treated as a first-class citizen with AES encryption primitives, enabling a "Vault" architecture where API keys are decrypted only in memory during inference.

### Data Flow

The internal logic operates as a series of **Interceptors**.

1.  **Request Arrival**: When a request arrives, it is authenticated.
2.  **Budget Gatekeeper**: Checks if the user has sufficient budget.
3.  **Inference Proxy**: The request is forwarded to the LLM via `litellm`.
4.  **PII Sentinel**: The response is scrubbed for PII *before* logging.
5.  **Logging**: The sanitized payload is written to the immutable audit log.

### Component Diagram

```mermaid
graph LR
    User[User/Client] --> API[Coreason API]
    API --> Auth[Auth & RBAC]
    API --> Budget[Budget Guardrail]
    Budget -->|Allowed| Proxy[Inference Proxy]
    Budget -->|Blocked| 402[402 Payment Required]
    Proxy --> LLM[External LLM Provider]
    LLM --> Proxy
    Proxy --> PII[PII Scrubber]
    PII --> Logs[Immutable Logs (DB)]
    PII --> User
```
