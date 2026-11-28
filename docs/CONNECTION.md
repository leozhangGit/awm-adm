# Provider connection API

One connection supplies remote interpretation, acquisition, extraction and explanation. Provider choice and model identifier are explicit configuration. They do not select domain rules, change local validation or require a pricing catalog.

`GET /api/v1/connection` returns the saved provider/model, a saved-key indicator, current state, configuration generation, any activation error and the gateway's public encryption key. It never returns the saved credential. Connection endpoints use the shared trusted local workspace boundary.

Submit `POST /api/v1/connection/enable` with a stable `idempotency_key`, `provider` (`openai` or `anthropic`), `model`, and either a new encrypted credential with its `sealing_key_id` or no credential fields to reuse the saved key. The encryption envelope contains `credential`, `provider` and the same `idempotency_key`, sealed with the gateway's RSA-OAEP-SHA256 key and its existing `awm-adm-provider-credential/1` label. The application stores ciphertext; only the gateway decrypts it. A provider change requires a replacement credential.

The returned operation progresses through credential synchronization and one bounded test. A complete successful response enables the exact configuration. Failure leaves it disabled with a diagnostic. If no worker claims the test before its dispatch deadline, it finishes as `not_dispatched` without a provider call; it does not remain indefinitely in Testing. Inspect `/api/v1/connection/operations/{id}` or the connection state; reading them never sends a test. Repeating an identical submission recovers the original operation instead of another call. Changing content under the same identity conflicts.

`POST /api/v1/connection/disable` takes a stable `idempotency_key`. It fences new remote dispatch immediately, retains the configuration/key and permits editing. A late successful test cannot undo Disable. Already dispatched calls retain their outcomes; uncertain calls are never automatically repeated. Accepted structured model queries remain available independently of the gateway.

There are no purpose checklists, price-installation requirements, monetary allowances or financial quotas in connection activation/dispatch. Internal purpose tags route work. Finite output/time bounds, task attempts, scheduling, authenticated dispatch and cancellation remain operational controls. Enabling is a connection check, not a guarantee that every acquisition will succeed.

## Usage

Call failure does not itself disable the connection. [Provider diagnostics](PROVIDER_FAILURES.md) distinguish elapsed-time limits, network/process failures, reported HTTP errors and output-token exhaustion. All purposes share the six-minute provider timeout and token ceilings in [execution limits](LIMITS.md). Unknown completion or usage is retained without automatic retry.

`GET /api/v1/connection/usage?timezone=America%2FNew_York` returns seven calendar dates of known input/output tokens and 24 hourly outcome buckets. Each actual dispatch contributes once, including activation tests and failed calls. Queued or merely leased work is not counted as an active provider call. Known tokens from failures remain included; missing or unverified usage is counted separately. Active and unknown outcomes are separate from successes and failures. An expired lease with no confirmed outcome retains uncertainty rather than being reported as a known free call. Hour labels include offsets so daylight-saving folds remain distinct.

New calls use their dispatch authorization timestamp. Retained calls without that timestamp use their original creation time. Token usage is provider-reported evidence, not a reconstructed bill or proof that a zero-report call was free.

## Existing installations

Current schema 19 preserves connection versions, encrypted credentials and historical accounting. An upgrade from schema 16, 17 or 18 retains the saved connection state without testing it. Upgrades from older multi-connection stores initialize the single connection disabled: one existing configuration is retained automatically; multiple legacy configurations require choosing one before activation. Historical versions remain for provenance. The retired global enable, separate connection test, price and spending mutation endpoints cannot bypass this state machine.

A pending Enable retains its captured test limits. If an older operation lacks those fields, recovery can reattach the exact test grant already reserved under its identity. Without either captured limits or that existing grant, activation stops with `stale_context` and leaves the saved connection disabled. It does not adopt today's limits or send a test; a deliberate new Enable submission is required. Replaying the old submission only reads its retained outcome.

Use a paired pre-upgrade backup for rollback to an earlier schema; do not open a newer store with an older binary. Existing model artifacts retain their meaning. Snapshots with typed temporal evidence require the [service feature envelope](TEMPORAL_EVIDENCE.md), while legacy-only snapshots retain their existing transport.
