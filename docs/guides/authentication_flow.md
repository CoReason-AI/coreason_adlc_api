# Authentication Flow

This guide explains how to authenticate with the Coreason ADLC API using the supported flows. The API primarily relies on OIDC (OpenID Connect) for identity verification.

## Device Code Flow (SSO)

The API supports a standard Device Code flow suitable for CLI tools, desktop applications, and the Python Client SDK. This flow allows users to authenticate via their browser on a secondary device if necessary.

### How it Works

1.  **Initiation**: The client requests a device code.
2.  **User Action**: The user visits a verification URI and enters a user code.
3.  **Polling**: The client polls the server until the user completes the action.
4.  **Token**: The server issues an Access Token (JWT).

### Using the Python SDK

The easiest way to authenticate is using the provided `ClientAuthManager`.

```python
from coreason_adlc_api.client_auth import ClientAuthManager

auth_manager = ClientAuthManager()

# This handles the entire flow:
# 1. Prints the URI and Code
# 2. Polls for the token
# 3. Saves the token securely in the system keyring
auth_manager.login()
```

### Manual Integration

If you are building a custom client, follow these steps:

#### Step 1: Initiate Flow

Send a POST request to `/api/v1/auth/device-code`.

```bash
curl -X POST https://api.coreason.ai/api/v1/auth/device-code
```

**Response:**
```json
{
  "device_code": "...",
  "user_code": "ABCD-1234",
  "verification_uri": "https://sso.example.com/device",
  "expires_in": 600,
  "interval": 5
}
```

#### Step 2: User Authorization

Display the `user_code` and `verification_uri` to the user.

#### Step 3: Poll for Token

Poll the token endpoint `/api/v1/auth/token` at the specified `interval`.

```bash
curl -X POST https://api.coreason.ai/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"device_code": "..."}'
```

*   **HTTP 400 (authorization_pending)**: User has not finished. Wait and retry.
*   **HTTP 400 (slow_down)**: You are polling too fast. Increase interval.
*   **HTTP 200 OK**: Authorization successful. Returns the token.

#### Step 4: Use the Token

Include the Access Token in the `Authorization` header of subsequent requests.

```bash
curl -H "Authorization: Bearer <ACCESS_TOKEN>" https://api.coreason.ai/api/v1/workbench/drafts
```
