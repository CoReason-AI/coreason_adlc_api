# Security & Code Audit Report

**Date:** 2025-02-14
**Target:** `coreason_adlc_api`
**Auditor:** Jules

## Executive Summary

The audit of `coreason_adlc_api` identified several issues across the Tier 1 (Security/Logic) and Tier 2 (Quality) categories. The most critical findings relate to **Client-Side Trust for Budgeting** and **Latency in Telemetry Logging**. Code quality is generally high with 100% test coverage and strict typing, but some tests rely heavily on mocks, potentially masking integration issues.

---

## Tier 1: Logic & Security (Critical)

### 1. Budget Bypass via Client Estimation
**Severity:** **High**
**File:** `src/coreason_adlc_api/routers/interceptor.py`
**Line:** 28, 48

**Description:**
The `ChatCompletionRequest` model accepts an optional `estimated_cost` field (default `0.01`). The `check_budget_guardrail` function uses this client-provided value to authorize the request *before* execution.
A malicious client can send `estimated_cost=0.000001` to bypass the budget check. While the *real* cost is calculated later for telemetry, the *blocking* gatekeeper relies on the user's input.

**Impact:**
Users can bypass budget limits ("Cloud Bill Shock"), violating requirement BG-01.

**Snippet:**
```python
class ChatCompletionRequest(BaseModel):
    # ...
    estimated_cost: float = 0.01  # Default value

# In router:
check_budget_guardrail(user.oid, request.estimated_cost)
```

### 2. Blocking Telemetry Logging (Latency)
**Severity:** **Medium**
**File:** `src/coreason_adlc_api/routers/interceptor.py`
**Line:** 102

**Description:**
The telemetry logging is awaited (`await async_log_telemetry(...)`) *before* the response is returned to the user. This adds unnecessary latency to the request, as the user must wait for the database write to complete.

**Impact:**
Degraded API performance (latency). If the telemetry database is slow, the user experience suffers directly.

**Snippet:**
```python
await async_log_telemetry(
    # ...
)
return cast(Dict[str, Any], response)
```

### 3. Shallow Copy in Recursive PII Scrubber
**Severity:** **Medium**
**File:** `src/coreason_adlc_api/middleware/pii.py`
**Line:** 137

**Description:**
The `scrub_pii_recursive` function uses an iterative approach with `data.copy()` (for dicts) and `data[:]` (for lists). While it creates a new container for the *current* level, it modifies the structure in-place.
More importantly, it relies on `scrub_pii_payload` for strings. If the input data contains immutable sequence types other than strings (e.g., `tuples` containing PII), they are ignored by the `else: target[k] = v` block and passed through unscrubbed.

**Impact:**
Potential PII leak if the input JSON (or internal object structure) contains PII within tuples or custom objects that are not `list` or `dict`.

### 4. Unverified Token Decoding in Auth Poll
**Severity:** **Low** (Mitigated by Trust Context)
**File:** `src/coreason_adlc_api/routers/auth.py`
**Line:** 105

**Description:**
The `poll_for_token` endpoint decodes the JWT with `verify_signature=False` to extract the user OID for database synchronization.
While the token is obtained directly from the IdP over TLS (trusting the channel), relying on unverified claims is generally a bad practice. If the IdP were compromised or spoofed (Man-in-the-Middle), the local DB could be polluted with fake users.
*Note:* The token is properly verified later in `interceptor.py`.

---

## Tier 2: Code Quality & Compliance

### 1. Type Safety: `Any` Usage in Critical Paths
**Severity:** **Medium**
**File:** `src/coreason_adlc_api/routers/interceptor.py`
**Line:** 118

**Description:**
The `chat_completions` endpoint returns `cast(Dict[str, Any], response)`. The `execute_inference_proxy` also returns `Any`.
This defeats the purpose of static typing for the API response contract. Changes to the upstream LLM response format might break consumers without warning.

### 2. Test Quality: "Testing the Mock"
**Severity:** **Low**
**File:** `tests/test_middleware_pii.py`
**Line:** 68

**Description:**
The `test_scrub_pii_entities_replacement` test mocks the `AnalyzerEngine` and manually constructs `RecognizerResult` objects with fixed indices.
This tests the *replacement logic* but not the *detection logic*. It does not verify that `Presidio` actually detects "555-0199" as a phone number. If the Presidio configuration is wrong (e.g., wrong language model), this test will still pass, but the system will fail to scrub in production.

### 3. Floating Point Currency Math
**Severity:** **Low**
**File:** `src/coreason_adlc_api/middleware/budget.py`
**Line:** 37

**Description:**
The Redis Lua script uses `INCRBYFLOAT` for budget tracking. Floating point arithmetic is imprecise for currency (`0.1 + 0.2 != 0.3`).
Over millions of transactions, this can lead to drift. It is standard practice to store currency as integers (cents/micros).

---

## Recommendations

1.  **Fix Budget Bypass:**
    *   **Short Term:** Server-side estimation (token counting) using `tiktoken` or similar before the check. Ignore client `estimated_cost` or treat it as a "hint" capped by a server-calculated max.
2.  **Optimize Telemetry:**
    *   Use `FastAPI.BackgroundTasks` to offload `async_log_telemetry` so the response returns immediately.
3.  **Harden PII Scrubber:**
    *   Extend `scrub_pii_recursive` to handle `tuple` or convert them to lists.
    *   Add a test case for overlapping PII entities to ensure the reverse-sort replacement works as intended.
4.  **Integration Testing:**
    *   Add a "Live" test marker that runs against a real Presidio instance (even if local) instead of mocking the engine, to verify configuration.
