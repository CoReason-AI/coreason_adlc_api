# **Coreason ADLC API \- Requirements Document**

`coreason-adlc-api` Middleware

# **Part 1: Business Requirements Document (BRD)**

## **1\. Business Goals & Objectives**

The `coreason-adlc-api` acts as the **Governance Enforcement Layer** between the developer's local environment (Tier 1\) and the sensitive Data Plane (Tier 3). It abstracts "Enterprise" complexity (Auth, Logging, PII Scanning) so the client can remain lightweight and fast.

| ID | Business Goal | Description | Success Metric |
| ----- | ----- | ----- | ----- |
| **BG-01** | **Centralized Budget Control** | Prevent "Cloud Bill Shock" from runaway agent loops or excessive testing. Move cost enforcement from the honor system (client-side) to a hard gate (server-side). | 100% of inference requests exceeding the daily user cap (e.g., $50) are rejected with `402 Payment Required`. |
| **BG-02** | **Toxic Telemetry Prevention** | Eliminate the legal liability of storing Personally Identifiable Information (PII) in permanent logs. We must "borrow" **Microsoft Presidio** to scrub data *in-stream* before it rests in the database. | Zero PII detected in the `telemetry_logs` table during quarterly audits. |
| **BG-03** | **GxP & "Clean Room" Compliance** | Enforce Policy P-IP-001. Ensure strict attribution of every code change and inference call to a specific human identity, preventing anonymous or untraceable AI development. | 100% of `agent_drafts` and `telemetry_logs` are linked to a valid SSO Object (User UUID). |
| **BG-04** | **Deployment Flexibility** | Support the "Hybrid" nature of our workforce. The API must run identically on a developer's bare metal laptop (via `pip`) and in the secure Air Gap production cluster (via Docker). | Successful deployment using both `coreason-api start` (PyPI) and `docker run` (Container). |

## **2\. Stakeholder Needs (Middleware Focused)**

| Persona | Role | Requirement | API Capability Mapping |
| ----- | ----- | ----- | ----- |
| **System Administrator** | Ops | Needs to manage access control using existing corporate groups without managing local user accounts on the server. | **Identity Passthrough:** The API must validate SSO tokens and map SSO Groups to internal permissions (`group_mappings`). |
| **Compliance Officer** | Governance | Needs to ensure that when an employee is terminated, their "Orphaned Data" is immediately secured and not lost. | **Dead Man's Switch:** The API must support a "Quarantine" workflow triggered by User Termination status, scanning drafts for PII before transferring custody to a Manager. |
| **Engineering Manager** | Oversight | Needs to inspect a subordinate's locked session without risk of executing malicious "Trojan" code on their own machine. | **Safe View Protocol:** The API must serve drafts in `read_only` mode when accessed by a Manager breaking a lock. |
| **Security Architect** | InfoSec | Needs to ensure API keys for models (DeepSeek, OpenAI) are never stored on the developer's laptop. | **Vault Proxy:** The API handles all secret decryption in memory; the Client never sees the raw keys. |

## **3\. Compliance Constraints (P-IP-001)**

* **BC-01 (Air Gap Support):** The Middleware must assume it is the *only* component with outbound internet access. The Client (Streamlit) connects strictly to the Middleware via **TLS 1.3**.
* **BC-02 (Borrow to Build):** The Engineering team is **forbidden** from writing custom PII detection regex or custom LLM API clients. The Middleware **must** wrap `litellm` (for proxying) and `presidio-analyzer` (for scrubbing).
* **BC-03 (Dual Licensing):** The API must verify the presence of an Enterprise License Key at startup.
  * *Community Mode:* Features restricted to local storage.
  * *Enterprise Mode:* Enables SSO, Oracle/Postgres drivers, and Remote Vault.

# **Part 2: Functional Requirements Document (FRD)**

## **1\. Authentication & Authorization**

| ID | Requirement | Implementation Details |
| ----- | ----- | ----- |
| **FR-API-001** | **OAuth2 Device Code Flow** | The API must expose endpoints to initiate the Device Code flow with the SSO provider, enabling CLI/Headless authentication. • `POST /v1/auth/device-code`: Returns `user_code`, `verification_uri`. • `POST /v1/auth/token`: Polls for the JWT. |
| **FR-API-002** | **RBAC & Group Mapping** | On every request, the API must extract the `groups` claim from the JWT. It must query `identity.group_mappings` to determine which **AUC IDs** (Projects) the user is authorized to access. |
| **FR-API-003** | **Pessimistic Locking (Mutex)** | The API must enforce a mutex on `agent_drafts` to prevent concurrent edits. • **Lock:** On `GET /drafts/{id}`, set `locked_by_user=UUID` and `lock_expiry=NOW+30s`. • **Heartbeat:** `POST /drafts/{id}/lock` extends expiry. • **Conflict:** Return `423 Locked` if another user holds the lock. |
| **FR-API-004** | **Manager Override (Safe View)** | If a user with `Role: MANAGER` requests a locked draft: 1\. Allow the read. 2\. **Do not** acquire the write lock. 3\. Return a flag `mode: safe_view` in the JSON response, instructing the client to disable "Run" buttons. |

## **2\. Inference Proxy & Guardrails ("The Interceptor")**

**Logic Flow:** Request \-\> Budget \-\> LiteLLM \-\> Presidio \-\> Redis (Async) \-\> Response.

| ID | Requirement | Implementation Details |
| ----- | ----- | ----- |
| **FR-API-005** | **Budget Gatekeeper** | Before forwarding to LiteLLM, query the **LiteLLM Budget Manager** for the `user_uuid`. • **Condition:** If `daily_spend > limit` (e.g., $50), reject with `402 Payment Required`. • **Sync:** This check must be blocking. |
| **FR-API-006** | **Proxy & Determinism** | Forward the request to the model provider using **LiteLLM**. • **Constraint:** Force `temperature=0.0`. • **Constraint:** Inject the client-provided `seed` (or default to 42\) to ensure reproducibility. |
| **FR-API-007** | **In-Memory PII Scrubbing** | The API must pass the raw `request_payload` and the `response_payload` (from the model) to **Microsoft Presidio**. • **Action:** Replace detected entities (PHONE, PERSON, EMAIL) with `<REDACTED>`. • **Scope:** Memory only (do not write raw text to disk). |
| **FR-API-008** | **Async Telemetry Logging** | Push the **Scrubbed** payloads \+ metadata (Cost, Latency, AUC ID) to a **Redis Queue**. • **Worker:** A background task pops from Redis and writes to `telemetry_logs`. • **Goal:** Zero latency impact on the user response. |
| **FR-API-009** | **Safe Mode Validation** | The API must serve `GET /v1/system/compliance` returning the SHA256 hash of the server's authoritative `compliance.yaml`. This allows the client to verify "Safe Mode" integrity before importing libraries. |

## **3\. Data Persistence (Schema Requirements)**

The API is the sole owner of the PostgreSQL database.

| ID | Requirement | Schema / CRUD Logic |
| ----- | ----- | ----- |
| **FR-API-010** | **Identity Schema** | **`identity.users`**: Upsert user details on login. **`identity.group_mappings`**: Read-only (config managed) for mapping Idp OIDs to Roles. |
| **FR-API-011** | **Workbench Schema** | **`workbench.agent_drafts`**: • Store `oas_content` as **JSONB**. • Store `runtime_env` (pip freeze hash) to lock dependencies. • Maintain `agent_tools_index` for search optimization. • Implement `soft_delete` for archiving. |
| **FR-API-012** | **Telemetry Schema** | **`telemetry.telemetry_logs`**: • **Partition:** Partition by Day. • **Storage:** Use TOAST for large `request/response` JSONB columns. • **Immutable:** INSERT ONLY. |
| **FR-API-013** | **Vault Schema** | **`vault.secrets`**: • **Write:** Encrypt with AES-256 (Key from Env Var) before INSERT. • **Read:** Decrypt in memory only when constructing LiteLLM context. |

## **4\. Interface Specifications (REST API)**

*Base URL:* `/api/v1`

| Method | Endpoint | Description |
| ----- | ----- | ----- |
| **POST** | `/auth/device-code` | Initiates SSO Device Flow. |
| **POST** | `/auth/token` | Polls for Session Token (JWT). |
| **POST** | `/chat/completions` | **The Interceptor.** Accepts OpenAI-format chat messages. Handles Budget \-\> Proxy \-\> Scrub \-\> Log. |
| **GET** | `/workbench/drafts` | Returns list of drafts filterable by `auc_id`. |
| **GET** | `/workbench/drafts/{id}` | Returns draft content. **Triggers Lock Acquisition.** |
| **PUT** | `/workbench/drafts/{id}` | Updates draft content. **Requires active Lock.** |
| **POST** | `/workbench/drafts/{id}/lock` | Heartbeat to refresh lock expiry. |
| **POST** | `/vault/secrets` | Stores a new encrypted API key for a specific AUC. |
| **GET** | `/system/compliance` | Returns the `compliance.yaml` hash and allowlists. |

## **5\. Non-Functional Requirements (NFRs)**

| ID | Requirement | Implementation Details |
| ----- | ----- | ----- |
| **FR-API-SEC-01** | **Transport Security** | All connections must be **TLS 1.3**. Plaintext HTTP is forbidden (except `localhost`). |
| **FR-API-SEC-02** | **Memory Hygiene** | Secrets and PII must be garbage collected immediately after the request scope ends. No persistence in global variables. |
| **FR-API-DEP-01** | **Hybrid Distro** | • **PyPI:** `pip install coreason-adlc-api` must expose a CLI entry point (`coreason-api start`) that runs Uvicorn. • **Docker:** Container must be based on a hardened minimal image (e.g., `distroless`) exposing port 8000\. |
| **FR-API-PERF-01** | **Latency Budgets** | The overhead of the "Interceptor" (Budget Check \+ Presidio Scan) must not exceed **200ms** (excluding Model Inference time). |
| **FR-API-RES-01** | **Circuit Breaker** | Wrap `litellm` calls in a Circuit Breaker state machine (e.g., using `pybreaker`). • **Threshold:** If 5 errors occur in 10 seconds, Open the circuit. • **Fallback:** Immediately return `503 Service Unavailable` without calling the provider for 60 seconds. |

# **Part 3: Python Package Design Specification**

This section defines the internal logic structure for the `coreason-adlc-api` Python package. This specification is intended for use by LLM Agents to generate the implementation.

## **1\. Module: `coreason.middleware.interceptor`**

**Responsibility:** The core wrapper that sits between the User and the LLM.

| Function Name | Inputs (Type Hint) | Process Description | Output (Type Hint) |
| ----- | ----- | ----- | ----- |
| `check_budget_guardrail` | `user_id: UUID`, `estimated_cost: float` | 1\. Fetch current daily spend from Redis/DB. 2\. `if current + estimated > limit`: Raise `BudgetExceededError`. 3\. This is a *blocking* check. | `bool` (True if pass) |
| `scrub_pii_payload` | `text_payload: str` | 1\. Initialize `PresidioAnalyzer`. 2\. Scan for entities `[PHONE, EMAIL, PERSON]`. 3\. Replace findings with `<REDACTED {ENTITY_TYPE}>`. 4\. **CRITICAL:** Do not log original text. | `str` (Scrubbed Text) |
| `execute_inference_proxy` | `messages: List[Dict]`, `model: str`, `user_context: Dict` | 1\. Decrypt API Key for `mode l` from `Vault` (in memory). 2\. Inject `temperature=0.0`. 3\. Call `litellm.completion()`. 4\. Catch errors and map to HTTP codes. | `LiteLLMResponse` object |
| `async_log_telemetry` | `user_id: UUID`, `input: str`, `output: str`, `meta: Dict` | 1\. Create a `TelemetryLog` object. 2\. Push to Redis Queue `telemetry_queue`. 3\. Return immediately (fire-and-forget). | `None` |

## **2\. Module: `coreason.workbench.locking`**

**Responsibility:** Handling concurrency and the "Safe View" protocol.

| Function Name | Inputs (Type Hint) | Process Description | Output (Type Hint) |
| ----- | ----- | ----- | ----- |
| `acquire_draft_lock` | `draft_id: UUID`, `user_id: UUID` | 1\. Start DB Transaction. 2\. Select row `FOR UPDATE`. 3\. `if locked_by != None AND locked_by != user_id AND expiry > NOW`: Raise `LockConflictError`. 4\. Else: Update `locked_by=user_id`, `expiry=NOW+30s`. | `bool` (True if acquired) |
| `resolve_access_mode` | `draft_id: UUID`, `user_id: UUID`, `roles: List[str]` | 1\. Check lock status. 2\. `if locked_by == other_user`:   a. `if 'MANAGER' in roles`: Return `SAFE_VIEW` (Read-only override).   b. Else: Raise `423 Locked`. 3\. Else: Return `EDIT_MODE`. | `Enum('EDIT', 'SAFE_VIEW')` |

## **3\. Module: `coreason.auth.identity`**

**Responsibility:** Managing SSO flows and JWT parsing.

| Function Name | Inputs (Type Hint) | Process Description | Output (Type Hint) |
| ----- | ----- | ----- | ----- |
| `parse_and_validate_token` | `auth_header: str` | 1\. Strip `Bearer` prefix. 2\. Verify signature against Idp JWKS. 3\. Extract `oid` (Object ID) and `groups`. | `UserIdentity` object |
| `map_groups_to_projects` | `group_oids: List[str]` | 1\. Query `identity.group_mappings`. 2\. Flatten `allowed_auc_ids` arrays. 3\. Deduplicate results. | `List[str]` (Allowed AUCs) |

## **4\. Module: `coreason.vault.crypto`**

**Responsibility:** AES-256 encryption for API keys.

| Function Name | Inputs (Type Hint) | Process Description | Output (Type Hint) |
| ----- | ----- | ----- | ----- |
| `encrypt_secret` | `raw_value: str` | 1\. Load `ENCRYPTION_KEY` from env vars. 2\. Generate random IV (Initialization Vector). 3\. AES-GCM Encrypt. 4\. Return `b64encode(iv + ciphertext)`. | `str` (Encrypted String) |
| `decrypt_secret` | `encrypted_value: str` | 1\. Decode Base64. 2\. Extract IV (first 12/16 bytes). 3\. AES-GCM Decrypt. 4\. Return raw string. | `str` (Raw API Key) |

# **Appendix: Database Schema (DDL)**

The following PostgreSQL DDL commands satisfy the schema requirements defined in Section 3\.

### **6.1 Schema Setup**

CREATE SCHEMA IF NOT EXISTS identity;
CREATE SCHEMA IF NOT EXISTS workbench;
CREATE SCHEMA IF NOT EXISTS telemetry;
CREATE SCHEMA IF NOT EXISTS vault;

### **6.2 Identity & Access Management (FR-API-010)**

CREATE TABLE identity.users (
    user\_uuid UUID PRIMARY KEY,
    email VARCHAR(255) NOT NULL UNIQUE,
    full\_name VARCHAR(255),
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    last\_login TIMESTAMP WITH TIME ZONE
);

CREATE TABLE identity.group\_mappings (
    mapping\_id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),
    sso\_group\_oid UUID NOT NULL UNIQUE, \-- IdP Object ID
    role\_name VARCHAR(50) NOT NULL, \-- e.g., 'MANAGER', 'DEVELOPER'
    allowed\_auc\_ids TEXT\[\], \-- Array of Project IDs
    description VARCHAR(255)
);

### **6.3 Workbench & Locking (FR-API-003, FR-API-011)**

CREATE TABLE workbench.agent\_drafts (
    draft\_id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),
    user\_uuid UUID REFERENCES identity.users(user\_uuid),
    auc\_id VARCHAR(50) NOT NULL,
    title VARCHAR(255) NOT NULL,

    \-- Content & Versioning
    oas\_content JSONB NOT NULL, \-- Stores the Agent definition
    runtime\_env VARCHAR(64), \-- Pip freeze hash for environment consistency

    \-- Search Optimization
    agent\_tools\_index TSVECTOR,

    \-- Pessimistic Locking Fields
    locked\_by\_user UUID REFERENCES identity.users(user\_uuid),
    lock\_expiry TIMESTAMP WITH TIME ZONE,

    \-- Lifecycle
    is\_deleted BOOLEAN DEFAULT FALSE,
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),
    updated\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW()
);

\-- Index for fast searching of agent tools
CREATE INDEX idx\_drafts\_gin ON workbench.agent\_drafts USING GIN (agent\_tools\_index);
\-- Index for filtering by Project
CREATE INDEX idx\_drafts\_auc ON workbench.agent\_drafts(auc\_id);

### **6.4 Telemetry & Compliance (FR-API-008, FR-API-012)**

CREATE TABLE telemetry.telemetry\_logs (
    log\_id UUID DEFAULT gen\_random\_uuid(),
    timestamp TIMESTAMP WITH TIME ZONE NOT NULL DEFAULT NOW(),

    \-- Metadata
    user\_uuid UUID, \-- Nullable if auth fails, but tracked for billing
    auc\_id VARCHAR(50),
    model\_name VARCHAR(100),

    \-- Payloads (Scrubbed by Presidio)
    request\_payload JSONB,
    response\_payload JSONB,

    \-- Metrics
    cost\_usd DECIMAL(10, 6),
    latency\_ms INTEGER
) PARTITION BY RANGE (timestamp);

\-- Storage optimization for large JSON payloads
ALTER TABLE telemetry.telemetry\_logs ALTER COLUMN request\_payload SET STORAGE EXTENDED;
ALTER TABLE telemetry.telemetry\_logs ALTER COLUMN response\_payload SET STORAGE EXTENDED;

\-- Example Partition (Automated via Cron/pg\_partman in Prod)
CREATE TABLE telemetry.telemetry\_logs\_2024\_10\_27 PARTITION OF telemetry.telemetry\_logs
    FOR VALUES FROM ('2024-10-27 00:00:00+00') TO ('2024-10-28 00:00:00+00');

### **6.5 Secure Vault (FR-API-013)**

CREATE TABLE vault.secrets (
    secret\_id UUID PRIMARY KEY DEFAULT gen\_random\_uuid(),
    auc\_id VARCHAR(50) NOT NULL,
    service\_name VARCHAR(50) NOT NULL, \-- e.g., 'openai', 'deepseek'

    \-- Security
    encrypted\_value TEXT NOT NULL, \-- Must be AES-256 Encrypted
    encryption\_key\_id VARCHAR(50), \-- Reference to key version (optional rotation support)

    created\_by UUID REFERENCES identity.users(user\_uuid),
    created\_at TIMESTAMP WITH TIME ZONE DEFAULT NOW(),

    UNIQUE(auc\_id, service\_name) \-- Prevent duplicate keys for same service/project
);
