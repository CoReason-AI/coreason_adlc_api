# System API

The System module provides utility and compliance endpoints.

## Endpoints

### 1. Compliance Status

Returns the SHA256 checksum of the server's authoritative compliance definition (`compliance.yaml`). This allows clients to verify they are interacting with a compliant "Safe Mode" environment.

*   **URL**: `/api/v1/system/compliance`
*   **Method**: `GET`
*   **Auth Required**: No

**Response**:

```json
{
  "checksum_sha256": "e3b0c442...",
  "allowlists": {
    "libraries": ["numpy", "pandas"],
    "urls": ["*.coreason.ai"]
  }
}
```
