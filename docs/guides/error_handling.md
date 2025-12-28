# Error Handling

The Coreason ADLC API uses standard HTTP status codes combined with a structured error response format.

## Standard Error Response

All API errors return a JSON body with a `detail` field explaining the error.

```json
{
  "detail": "Budget exceeded for user 1234-..."
}
```

Some errors may include additional fields depending on the context.

## HTTP Status Codes

| Code | Description | Meaning |
| :--- | :--- | :--- |
| `200` | OK | The request succeeded. |
| `201` | Created | The resource was successfully created. |
| `400` | Bad Request | The request was malformed or invalid. |
| `401` | Unauthorized | Authentication is required or failed. |
| `402` | Payment Required | **Budget Exceeded**. The user has hit their daily limit. |
| `403` | Forbidden | Authenticated, but lacking permission (RBAC) for the project. |
| `404` | Not Found | The requested resource does not exist. |
| `422` | Validation Error | The request body failed schema validation. |
| `423` | Locked | Resource is locked by another user (Workbench Drafts). |
| `429` | Too Many Requests | Rate limit exceeded. |
| `500` | Internal Server Error | An unexpected error occurred on the server. |
| `502/503/504` | Service Unavailable | Upstream LLM provider or database issue. |

## Domain Exception Mapping (Python SDK)

The Python Client SDK (`CoreasonClient`) automatically maps these HTTP status codes to a specific hierarchy of Python exceptions defined in `coreason_adlc_api.exceptions`.

### Exception Hierarchy

*   `CoreasonError` (Base Class)
    *   `ClientError` (4xx)
        *   `AuthenticationError` (401/403)
        *   `BudgetExceededError` (402)
        *   `ComplianceViolationError` (422)
        *   `RateLimitError` (429)
    *   `ServerError` (5xx)
        *   `ServiceUnavailableError` (502/503/504)

### Handling Exceptions

When using the `CoreasonClient`, you should catch these specific exceptions to handle errors gracefully.

```python
from coreason_adlc_api.client import CoreasonClient
from coreason_adlc_api.exceptions import BudgetExceededError, AuthenticationError

client = CoreasonClient()

try:
    response = client.get("/api/v1/workbench/drafts")
except BudgetExceededError:
    print("You have run out of budget for today.")
except AuthenticationError:
    print("Please login again.")
except CoreasonError as e:
    print(f"An unexpected API error occurred: {e}")
```
