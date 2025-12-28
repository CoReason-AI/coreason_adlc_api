# Compliance Audit Guide

This document is intended for Quality Assurance (QA) and Compliance Auditors verifying the **Coreason ADLC API** against GxP and corporate governance policies (P-IP-001).

## 1. Business Goal Verification Matrix

The following table maps the Business Goals (BG) defined in the Requirements to specific audit evidence.

| ID | Business Goal | Audit Verification Procedure | Evidence Artifact |
| :--- | :--- | :--- | :--- |
| **BG-01** | **Centralized Budget Control** | 1. Simulate a user exceeding their daily limit ($50).<br>2. Attempt an inference request.<br>3. Verify HTTP 402 response. | Server Logs showing `402 Payment Required`. <br> Redis `budget:{date}:{user_id}` key value. |
| **BG-02** | **Toxic Telemetry Prevention** | 1. Send a request containing a known PII string (e.g., "Phone 555-0199").<br>2. Query `telemetry_logs` table.<br>3. Confirm text is stored as `<REDACTED PHONE_NUMBER>`. | `telemetry.telemetry_logs` database record. |
| **BG-03** | **GxP Compliance (Attribution)** | 1. Review `agent_drafts` and `telemetry_logs`.<br>2. Verify every record has a non-null `user_uuid` linked to `identity.users`. | SQL Query Result: `SELECT count(*) FROM telemetry_logs WHERE user_uuid IS NULL` (Should be 0). |
| **BG-04** | **Deployment Flexibility** | 1. Verify successful startup in Docker (Air Gap simulation).<br>2. Verify successful startup via Pip (Developer Laptop). | Screenshot of `coreason-api start` output in both environments. |

## 2. Auditing "Toxic Telemetry" (BG-02)

To verify that PII is being scrubbed from logs, an auditor can perform the following SQL query on the `telemetry` database.

**Verification Query:**

```sql
SELECT
    log_id,
    request_payload->>'content' as logged_content
FROM
    telemetry.telemetry_logs
WHERE
    request_payload::text LIKE '%<REDACTED%';
```

**Expected Result:**
The query should return rows where sensitive entities have been replaced. If you search for the original raw PII (e.g., a specific real phone number used in a test), it **must not** return any results.

## 3. Auditing "Dead Man's Switch" & Access Control

### Verifying Access Revocation
When a user is removed from the SSO Group (Entra ID):

1.  **Action**: Remove user from the AD Group.
2.  **Test**: User attempts to call `GET /workbench/drafts`.
3.  **Expected Result**: The API re-validates the `groups` claim and the `group_mappings` table. Access is denied (HTTP 403) immediately or upon token refresh, depending on configuration.

*Note: The system relies on the `map_groups_to_projects` function which runs on **every request**, ensuring near real-time revocation.*

### Verifying "Safe View" (Manager Access)
To prove that managers cannot accidentally alter code ("Trojan Horse" prevention):

1.  **Action**: Have a Manager (Role: MANAGER) access a draft locked by a Developer.
2.  **Observation**: The API returns `mode: SAFE_VIEW`.
3.  **Test**: The Frontend Client disables "Edit" and "Run" buttons.
4.  **Backend Verification**: Attempt a `PUT` request as the Manager. It should fail with `403 Forbidden` or `423 Locked` (depending on exact implementation state logic) if they try to write without holding the lock.

## 4. Software Bill of Materials (SBOM)

For GxP validation, the exact version of the software must be known.

Run the following to generate the SBOM of the installed environment:

```bash
pip freeze > requirements_audit.txt
```

Verify that `coreason-adlc-api` matches the expected release version.
