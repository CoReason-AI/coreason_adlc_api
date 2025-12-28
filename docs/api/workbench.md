# Workbench API

The Workbench module manages the lifecycle of Agent Drafts, including creation, editing, locking, and approval workflows.

## Common Errors

*   `403 Forbidden`: User does not have access to the specified project (`auc_id`).
*   `404 Not Found`: Draft ID does not exist.
*   `423 Locked`: The draft is currently locked by another user.

## Endpoints

### 1. List Drafts

Retrieves a list of drafts for a specific project.

*   **URL**: `/api/v1/workbench/drafts`
*   **Method**: `GET`
*   **Auth Required**: Yes

**Query Parameters**:

*   `auc_id`: The Project ID to filter by.

**Response**: List of `DraftResponse` objects.

### 2. Create Draft

Creates a new agent draft.

*   **URL**: `/api/v1/workbench/drafts`
*   **Method**: `POST`
*   **Auth Required**: Yes

**Request Body** (`DraftCreate`):

```json
{
  "auc_id": "proj-123",
  "title": "My New Agent",
  "content": "Agent definition..."
}
```

### 3. Get Draft

Retrieves a specific draft by ID and attempts to acquire a lock.

*   **URL**: `/api/v1/workbench/drafts/{draft_id}`
*   **Method**: `GET`
*   **Auth Required**: Yes

### 4. Update Draft

Updates the content of an existing draft. Requires the user to hold the lock.

*   **URL**: `/api/v1/workbench/drafts/{draft_id}`
*   **Method**: `PUT`
*   **Auth Required**: Yes

**Request Body** (`DraftUpdate`):

```json
{
  "title": "Updated Title",
  "content": "Updated content..."
}
```

### 5. Refresh Lock

Extends the lock duration for a draft.

*   **URL**: `/api/v1/workbench/drafts/{draft_id}/lock`
*   **Method**: `POST`
*   **Auth Required**: Yes

### 6. Submit Draft

Submits a draft for approval (transitions to `PENDING`).

*   **URL**: `/api/v1/workbench/drafts/{draft_id}/submit`
*   **Method**: `POST`
*   **Auth Required**: Yes

### 7. Approve Draft

Approves a pending draft (transitions to `APPROVED`). Requires `MANAGER` role.

*   **URL**: `/api/v1/workbench/drafts/{draft_id}/approve`
*   **Method**: `POST`
*   **Auth Required**: Yes (Manager)

### 8. Reject Draft

Rejects a pending draft (transitions to `REJECTED`). Requires `MANAGER` role.

*   **URL**: `/api/v1/workbench/drafts/{draft_id}/reject`
*   **Method**: `POST`
*   **Auth Required**: Yes (Manager)
