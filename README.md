# coreason_adlc_api

Secure ADLC Middleware enforcing PII scrubbing, budget caps, and strict governance.

[![CI](https://github.com/CoReason-AI/coreason_adlc_api/actions/workflows/ci.yml/badge.svg)](https://github.com/CoReason-AI/coreason_adlc_api/actions/workflows/ci.yml)

## The Architecture and Utility of coreason_adlc_api

### 1. The Philosophy (The Why)

In the high-stakes environment of biopharmaceutical development, we face a critical tension: the need for rapid AI innovation versus the absolute requirement for GxP compliance, data sovereignty, and auditability. The standard approach—allowing developers direct access to model APIs—creates a "Black Box" liability where costs spiral and decision provenance is lost.

We architected the **coreason_adlc_api** to resolve this by shifting governance from a client-side "honor system" to a server-side "hard gate." Our intent is to prevent "Toxic Telemetry" and "Cloud Bill Shock" while ensuring that every AI-generated insight is inextricably linked to a human identity. This middleware acts as a "Clean Room" airlock, securing the data plane without hindering developer velocity.

### 2. Under the Hood (The Dependencies & Logic)

The architecture leverages a stack chosen for concurrency, security, and integration rather than raw generative capability:

* **fastapi & uvicorn**: The backbone is asynchronous, designed to handle high-concurrency inference requests without blocking the application logic.
* **litellm**: This dependency underscores our "Borrow to Build" mandate. Instead of writing custom clients for every model provider, we use litellm as a universal proxy, allowing the middleware to intercept payloads regardless of the underlying model.
* **presidio-analyzer & spacy**: These libraries provide the "scrubbing" intelligence. By integrating Microsoft’s Presidio directly into the memory stream, we ensure that PII detection happens locally and in-memory, intercepting sensitive data before it ever touches a disk. *Note: PII scrubbing requires Python < 3.14.*
* **redis & asyncpg**: Performance is critical. redis handles high-speed, atomic budget counting, while asyncpg ensures non-blocking writes to the immutable PostgreSQL audit logs.
* **cryptography**: Security is treated as a first-class citizen with AES encryption primitives, enabling a "Vault" architecture where API keys are decrypted only in memory during inference.

The internal logic operates as a series of **Interceptors**. When a request arrives, it passes through the **Budget Gatekeeper** and **Identity Validator** before the **PII Sentinel** scans it. Only then is the request proxied to the LLM. The response travels back through the same scrubber, ensuring the **Immutable Execution Record (IER)** contains only sanitized, safe data.

### 3. In Practice (The How)

The utility of coreason_adlc_api is best understood through its enforcement mechanisms. These examples illustrate how the middleware creates a safe environment for AI execution.

#### The Budget Guardrail

Before any inference occurs, the system performs an atomic check against a user's daily limit. This prevents infinite loops or excessive testing from draining resources.

```python
from coreason_adlc_api.middleware.budget import check_budget_guardrail
from uuid import uuid4

# In the request lifecycle, before calling the LLM:
user_id = uuid4()
estimated_cost = 0.05  # Cost derived from token count

try:
    # This is a blocking check backed by Redis.
    # It atomically increments the spend and reverts if the limit is hit.
    allowed = check_budget_guardrail(user_id, estimated_cost)

    print(f"Request allowed. Processing inference for user {user_id}...")

except Exception as e:
    # 402 Payment Required is raised to the client
    print(f"Governance Block: {e}")
```

#### In-Stream PII Scrubbing

To prevent "Toxic Telemetry," the API scrubs payloads in memory using a Singleton analyzer to avoid reload overhead.

```python
from coreason_adlc_api.middleware.pii import scrub_pii_payload

# A raw payload containing sensitive data enters the system
raw_payload = "Patient John Doe called from 555-0199 regarding adverse effects."

# The Scrubber intercepts the text before it is written to telemetry logs
safe_payload = scrub_pii_payload(raw_payload)

# The output preserves structure but obliterates identity
# Output: "Patient <REDACTED PERSON> called from <REDACTED PHONE_NUMBER> regarding adverse effects."
print(f"Loggable Payload: {safe_payload}")
```

#### Pessimistic Locking for Collaboration

To enforce the "Single Author" principle of the ADLC, the workbench router enforces strict locking. This ensures that while multiple users can view a draft, only one can edit it at a time.

```python
# Inside coreason_adlc_api/routers/workbench.py

@router.put("/drafts/{draft_id}")
async def update_existing_draft(draft_id: UUID, update: DraftUpdate, identity: UserIdentity):
    """
    Updates draft content, but only if the user holds the lock.
    """
    # 1. Fetch the draft metadata efficiently
    current_draft = await get_draft_by_id(draft_id, identity.oid)

    # 2. Verify Project Access (RBAC)
    # Ensures the user belongs to the Entra ID group assigned to this AUC
    await _verify_project_access(identity, current_draft.auc_id)

    # 3. Commit the update
    # If the draft is locked by another user, the service layer raises a 423 Locked error
    return await update_draft(draft_id, update, identity.oid)
```

## Getting Started

### Prerequisites

- Python 3.12+ (3.12 or 3.13 recommended for full PII features)
- Poetry

### Installation

**Option A: For Development (Source)**
1.  Clone the repository:
    ```sh
    git clone https://github.com/CoReason-AI/coreason_adlc_api
    cd coreason_adlc_api
    ```
2.  Install dependencies:
    ```sh
    poetry install
    ```

**Option B: For Deployment (Pip)**
1.  Install via pip:
    ```sh
    pip install coreason-adlc-api
    ```

### Usage

-   **Start the server:**
    ```sh
    coreason-api start
    ```
-   **Run the linter (Dev):**
    ```sh
    poetry run pre-commit run --all-files
    ```
-   **Run the tests (Dev):**
    ```sh
    poetry run pytest
    ```
