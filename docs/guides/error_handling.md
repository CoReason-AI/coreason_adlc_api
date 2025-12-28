# Error Handling

The Coreason ADLC API uses standard HTTP status codes to indicate the success or failure of a request.

## Common Status Codes

| Code | Description | Meaning |
| :--- | :--- | :--- |
| `200` | OK | The request succeeded. |
| `201` | Created | The resource was successfully created. |
| `400` | Bad Request | The request was malformed or invalid. |
| `401` | Unauthorized | Authentication is required or failed. |
| `403` | Forbidden | Authenticated, but you do not have permission (RBAC). |
| `404` | Not Found | The requested resource does not exist. |
| `422` | Validation Error | The request body failed schema validation. |
| `500` | Internal Server Error | An unexpected error occurred on the server. |

## Specific Error Conditions

### 402 Payment Required (Budget Exceeded)

If a user exceeds their daily budget limit, the Interceptor will return a `402` error.

```json
{
  "detail": "Budget exceeded"
}
```

**Resolution**: Wait for the daily reset (UTC midnight) or request a budget increase.

### 423 Locked (Resource Locked)

When editing drafts in the Workbench, a pessimistic lock is used. If you try to edit a draft locked by another user, you will receive a `423` error.

```json
{
  "detail": "Draft is locked by another user"
}
```

**Resolution**: Wait for the lock to expire or for the other user to finish editing.

### 403 Forbidden (RBAC)

If you attempt to access a project (`auc_id`) that is not mapped to your SSO groups, you will receive a `403`.

```json
{
  "detail": "User is not authorized to access project <auc_id>"
}
```

**Resolution**: Request access to the project via your Identity Provider group membership.
