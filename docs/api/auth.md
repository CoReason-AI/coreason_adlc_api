# Authentication API

The Authentication module handles identity verification and session management. It currently supports a mocked SSO device flow for development.

## Endpoints

### 1. Initiate Device Code Flow

Initiates the SSO Device Code flow. In a real environment, this would interface with an IdP like Azure AD or Auth0.

*   **URL**: `/api/v1/auth/device-code`
*   **Method**: `POST`
*   **Auth Required**: No

**Response**:

```json
{
  "device_code": "5f6a9b...",
  "user_code": "ABCD-1234",
  "verification_uri": "https://sso.example.com/device",
  "expires_in": 600,
  "interval": 5
}
```

### 2. Poll for Token

Exchanges a device code for a session token (JWT).

*   **URL**: `/api/v1/auth/token`
*   **Method**: `POST`
*   **Auth Required**: No

**Request Body**:

```json
{
  "device_code": "5f6a9b..."
}
```

**Response**:

```json
{
  "access_token": "eyJhbGciOi...",
  "token_type": "Bearer",
  "expires_in": 3600
}
```

**Note**: In the current mocked implementation, this endpoint generates a valid self-signed JWT using the local `JWT_SECRET` and ensures a mock user exists in the database.
