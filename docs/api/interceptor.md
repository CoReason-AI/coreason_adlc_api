# Interceptor API

The Interceptor module is the core of the ADLC middleware, handling inference requests with governance checks.

## Endpoints

### 1. Chat Completions

Proxies a chat completion request to an LLM provider, enforcing budget and PII scrubbing.

*   **URL**: `/api/v1/chat/completions`
*   **Method**: `POST`
*   **Auth Required**: Yes

**Request Body** (`ChatCompletionRequest`):

```json
{
  "model": "gpt-4",
  "messages": [
    {"role": "user", "content": "Hello, world!"}
  ],
  "auc_id": "proj-123",
  "user_context": {"session_id": "xyz"},
  "estimated_cost": 0.01
}
```

**Flow**:
1.  **Budget Check**: Verifies if the user has sufficient daily budget. If not, returns `402 Payment Required`.
2.  **Inference**: Proxies the request to the model specified (via `litellm`).
3.  **PII Scrubbing**: Scrubs the input and output text for PII *before* logging to the audit database.
4.  **Logging**: Asynchronously logs the interaction.

**Response**:
Returns the raw JSON response from the underlying LLM provider (e.g., OpenAI format).
