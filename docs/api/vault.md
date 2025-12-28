# Vault API

The Vault module provides secure storage for API keys and secrets. Secrets are encrypted using AES-256 GCM before storage.

## Endpoints

### 1. Create or Update Secret

Encrypts and stores a new API key for a specific service and project.

*   **URL**: `/api/v1/vault/secrets`
*   **Method**: `POST`
*   **Auth Required**: Yes

**Request Body** (`CreateSecretRequest`):

```json
{
  "auc_id": "proj-123",
  "service_name": "openai",
  "raw_api_key": "sk-..."
}
```

**Response** (`SecretResponse`):

```json
{
  "secret_id": "a1b2c3d4-...",
  "auc_id": "proj-123",
  "service_name": "openai",
  "created_at": "2023-10-27T10:00:00Z"
}
```

**Security Note**: The `raw_api_key` is never returned in the response. It is decrypted only in memory within the Interceptor module during inference.
