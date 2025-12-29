# Potential Problems in `coreason-veritas` Integration

Based on the recent refactoring and testing of `coreason_adlc_api`, the following potential problems and friction points were identified in the `coreason-veritas` library (v0.2.0).

## 1. Dependency Constraints & Conflicts
*   **FastAPI Version Pinning:** The library appears to enforce `fastapi >= 0.128.0`. This forced an upgrade of the host application's FastAPI version, potentially destabilizing other dependencies.
*   **Wrapt Versioning:** Through its OpenTelemetry dependencies, it requires `wrapt < 2.0.0`. This conflicts with other modern libraries that might rely on newer `wrapt` versions (common in testing/mocking tools), leading to potential "dependency hell".

## 2. Side-Effects on Import
*   **Auto-Initialization of OpenTelemetry:** Merely importing `coreason-veritas` (or its submodules) seems to trigger OpenTelemetry auto-instrumentation or exporter initialization.
    *   **Impact:** Running tests without a local OTel collector (port 4318) results in connection refused error logs (`urllib3.exceptions.NewConnectionError`) spamming the console, even if telemetry is not explicitly used in that test context.
    *   **Workaround:** Setting `COREASON_VERITAS_TEST_MODE=1` helps, but side-effects on import are generally an anti-pattern.

## 3. Testing & Mocking Difficulties
*   **Eager Key Validation:** The `SignatureValidator` (used by `@governed_execution`) attempts to load the public key from the environment (`COREASON_VERITAS_PUBLIC_KEY`) and parse it as a PEM file immediately upon invocation.
    *   **Impact:** You cannot use a dummy string (e.g., "mock_key") in CI/test environments. The library raises `ValueError: Unable to load PEM file` or `AssetTamperedError` unless a syntactically valid PEM key is provided or the validator is deeply mocked.
    *   **Workaround:** Requires heavy mocking of `coreason_veritas.gatekeeper.SignatureValidator.verify_asset` in every test case involving the service layer.

## 4. Type Safety Issues
*   **Untyped Decorators:** The `@governed_execution` decorator lacks proper type annotations.
    *   **Impact:** `mypy` flags errors like `Untyped decorator makes function ... untyped` [misc] and `Returning Any from function declared to return ...` [no-any-return].
    *   **Workaround:** Requires adding `# type: ignore[misc]` and `# type: ignore[no-any-return]` directives throughout the codebase, reducing actual type safety in the service layer.

## 5. API Design & Coupling
*   **Argument Name Coupling:** The `@governed_execution` decorator relies on string inspection of argument names (`signature_arg="signature"`).
    *   **Impact:** The decorated service methods *must* accept these arguments explicitly, even if the service logic itself doesn't use them (e.g., passing `signature` just for the decorator to see it). This leaks infrastructure concerns into the business logic signatures.
*   **Draft Mode Implementation:** The legacy implementation handled signatures in headers, but the service layer now mandates them as arguments. This requires the Router to unpack headers and pass them as arguments, creating boilerplate.

## 6. Module Structure
*   **Import Confusion:** The prompt implied importing from `coreason_veritas.governance`, but the decorator was found at the top level `coreason_veritas` or required a different import path. (Verified: imported from `coreason_veritas`).

## 7. Error Handling
*   **Connection Errors:** If the OTel collector is down, the library prints stack traces to stderr/stdout during execution, which can clutter logs and alarm operators, instead of failing silently or logging a structured warning.
