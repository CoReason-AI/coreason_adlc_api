# Client SDK Guide

The `CoreasonClient` is a synchronous Python client designed for easy integration with scripts, notebooks, and Streamlit applications. It handles authentication, error mapping, and connection management.

## Initialization

The client is implemented as a Singleton. It automatically detects the API URL from the environment variable `COREASON_API_URL` (default: `http://localhost:8000`).

```python
from coreason_adlc_api.client import CoreasonClient

# Initialize
client = CoreasonClient()
```

## Authentication

The client integrates with `ClientAuthManager` to handle authentication automatically. It injects the `Authorization: Bearer <token>` header into every request (except auth endpoints).

If a token is missing or expired, you may need to trigger the login flow using the `ClientAuthManager` directly or handle the `AuthenticationError`.

```python
from coreason_adlc_api.client_auth import ClientAuthManager

auth = ClientAuthManager()
if not auth.get_token():
    auth.login()  # Starts the Device Code Flow
```

## Making Requests

The client exposes standard HTTP methods: `get`, `post`, `put`, `delete`. These methods return the raw `httpx.Response` object, allowing access to headers and binary content if needed.

### Setting the Project Context

Many endpoints require a Project ID (AUC ID) context.

```python
client.set_project("project-alpha-123")
```

### Examples

**Fetching Drafts:**

```python
try:
    response = client.get("/api/v1/workbench/drafts")
    drafts = response.json()
    print("Drafts:", drafts)
except CoreasonError as e:
    print(f"Error: {e}")
```

**Creating a Chat Completion:**

```python
payload = {
    "model": "gpt-4",
    "messages": [{"role": "user", "content": "Hello world"}],
    "auc_id": "project-alpha",
    "estimated_cost": 0.01
}

response = client.post("/api/v1/interceptor/chat/completions", json=payload)
print(response.json())
```

## Error Handling

The client automatically raises exceptions based on HTTP status codes. See [Error Handling](error_handling.md) for the full hierarchy.

## Low-Level Access

You can access the underlying `httpx.Client` if needed, though it is recommended to use the wrapper methods to ensure proper error handling.

```python
# Raw request (bypassing exception mapping)
response = client.client.get("...")
```
