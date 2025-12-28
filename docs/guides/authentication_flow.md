# Authentication Flow

This guide explains how to authenticate with the Coreason ADLC API using the supported flows.

## Device Code Flow (SSO)

The API supports a standard Device Code flow suitable for CLI tools and desktop applications.

### Step 1: Initiate Flow

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

### Step 2: User Authorization

Display the `user_code` and `verification_uri` to the user. The user opens the URL in their browser and enters the code to authorize the application.

### Step 3: Poll for Token

While the user is authorizing, your application should poll the token endpoint `/api/v1/auth/token` at the specified `interval`.

```bash
curl -X POST https://api.coreason.ai/api/v1/auth/token \
  -H "Content-Type: application/json" \
  -d '{"device_code": "..."}'
```

*   If authorization is pending, the server may return a "pending" error (standard OAuth behavior).
*   Once authorized, the server returns the Access Token.

### Step 4: Use the Token

Include the Access Token in the `Authorization` header of subsequent requests.

```bash
curl -H "Authorization: Bearer <ACCESS_TOKEN>" https://api.coreason.ai/api/v1/workbench/drafts
```
