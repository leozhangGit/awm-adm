# Application API

The service exposes model, learning, source, connection and conversational resources under `/api/v1` within AWM-ADM 0.4.0. See [local workspace access](LOCAL_ACCESS.md), [connection and usage](CONNECTION.md), [conversations](CONVERSATIONS.md) and [OpenAPI](../contracts/openapi.json).

The public API runs at `http://127.0.0.1:9527/api/v1`. It exposes independent ADM initialization, durable local requests, exact result bindings, owner settings/requirements, bounded model operations and retained events. The [browser console](CONSOLE.md) uses these same routes for owner workflows. [Bounded learning and provider dispatch](LEARNING.md) use separate owner-authorized resources. A gap alone does not create a provider grant: an explicit episode can attach eligible requests, retain their learning interests, and trigger a new local attempt after checked publication. Provider output is never substituted for a request result.

## Direct interaction resources

Historical structured queries support `lookup_fact` with `effective_at`, and `lookup_fact_period` with inclusive `effective_from` and exclusive `effective_to`. Both use canonical UTC instants, an `entity_id` and a `predicate`. Automatic Ask preserves calendar-date precision using the captured system timezone unless the user specifies one. See [temporal semantics](TEMPORAL_INTERPRETATION.md) and [sources](SOURCES.md) for full-period support requirements. Existing instant queries and stored artifact profiles are unchanged.

All paths below are relative to `/api/v1` and use the shared local workspace boundary.

| Resource | Purpose |
| --- | --- |
| `GET /connection` | Saved configuration and enabled/testing/disabled state, without its secret |
| `POST /connection/enable`, `/connection/disable` | Idempotent test-and-enable, or disable retaining the key |
| `GET /connection/operations/{id}`, `/connection/usage` | Activation progress and known/unknown call usage |
| `POST /adms/{adm}/ask`, `/teach` | Direct input: `text`, optional `attachments`, `reply_to` and `idempotency_key` |
| `GET /adms/{adm}/chat/{ask|teach}` | Stable channel history: default forward `after`; backward `direction=backward` with optional exclusive `before`; limit 1–100, chronological items with `sequence`, `next_cursor`, `has_more` |
| `GET /adms/{adm}/interactions/{id}` | Readable progress, local outcome and explanation |
| `POST /adms/{adm}/interactions/{id}/cancel` | Stop active work; preserve accepted knowledge and completed outcomes |
| `GET /adms/{adm}/activity` | Time/type/origin-filtered console/API history |
| `GET /adms/{adm}/knowledge` | Current accepted declaration/evidence search, revision-bound pages |
| `POST /adms/{adm}/source-queues` | Explicit managed source-only intake using direct-message input |
| `/adms/{adm}/conversations` | Retained exchange internals and legacy history reads |
| `/adms/{adm}/interpretation-sessions`, `/interpretations` | Explicit preview, clarification and confirmation APIs |
| `/adms/{adm}/attachments`, `/intake` | Immutable upload, selected originals and bounded producer routes |

For example, send `{"text":"Can one more item be borrowed when one is already borrowed and one is available?","idempotency_key":"question-1"}` to the model's Ask endpoint. Read the returned interaction until its outcome is ready. Teach accepts the same shape and automatically checks and publishes clear requests; `reply_to` associates a clarification with its original exchange. Ask cannot silently teach.

`GET /adms/{adm}/history-options` retains revision-bound historical lookup metadata. Existing structured requests, requirements, snapshots, sources, feeds, proofs and diagnostic APIs remain available. Manual chat setup/decisions/renewal, separate connection-test/global-enable controls and financial mutation routes are retired. Historical price/allowance reads remain for retained accounting, not permission to issue new work.

URL versioning remains `/api/v1` with no v2/v3 aliases. Core serialized profiles and snapshots are unchanged; owned operational schema is 17. Public health paths remain `/health/live` and `/health/ready`. See [Connection](CONNECTION.md), [Conversations](CONVERSATIONS.md) and [History](HISTORY.md).

## Open the local workspace

Fresh stores open without setup; ordinary updates preserve compatible runtime data and historical actor references.

The standard-library example client needs no login or API key:

```sh
python3 scripts/api_client.py /api/v1/adms
python3 scripts/api_client.py /api/v1/openapi.json > openapi.json
```

All retained public operations use the shared local HTTP boundary. Same-origin console and native local requests are accepted without user credentials. Foreign/null origins, cross-site requests, browser form mutations and off-host peers are rejected. Provider secrets remain masked; internal machine credentials remain private. See [Local workspace access](LOCAL_ACCESS.md). The `/auth/*` setup/login/session/password/recovery/token routes are retired.

`GET /system` includes `request_limits` and `local_service`: profile `awm-adm-local/1`, stable `installation_id`, `connection_ready` and a safe `reason`. Readiness makes no provider call. The plugin checks this contract before using its small operation subset; it does not expose every public route.

## Instances and model operations

Create `create.json`:

```json
{"idempotency_key":"my-first-adm","name":"My first ADM","mode":"backward"}
```

```sh
python3 scripts/api_client.py /api/v1/adms --method POST --body create.json
python3 scripts/api_client.py /api/v1/operations/OPERATION_UUID
```

Creation returns `202` and an operation resource. Poll until `succeeded` or `failed`. A successful operation identifies the new ADM; an empty ADM has no domain declarations. HTTP disconnect does not cancel creation or lose its durable identity.

| Route, relative to `/api/v1` | Contract |
| --- | --- |
| `GET /adms` | Bounded by configured instance count; scoped clients see only authorized instances. |
| `POST /adms` | Owner-only idempotent operation. Body has key, name, mode and optional `snapshot`. |
| `GET /operations` | Owner-only latest 50 metadata summaries, without snapshot bodies. |
| `GET /operations/{id}` | Owner operation status, resulting ADM identity or snapshot, and safe failure. |
| `GET /adms/{adm}` | Identity, mode, owner epoch, current revision and theory/support/policy identities, archived state. |
| `GET /adms/{adm}/capabilities` | Bounded local catalog computation; remote providers are unnecessary. |
| `GET /adms/{adm}/model[?revision=UUID]` | Scoped read of one immutable revision, its context, declarations and recorded artifact values. Does not rerun admission or assign proof status. |
| `GET /adms/{adm}/versions[?after=N&limit=N&order=asc]` | Immutable model/policy revision metadata; detail at `/versions/{revision}`. |
| `GET/PUT /adms/{adm}/requirements` | Inspect or locally check and install the owner policy. PUT requires `expected_epoch`. |
| `PATCH /adms/{adm}/settings` | Owner `{expected_epoch, mode}`; forward/backward changes affect future decisions. |
| `POST /adms/{adm}/archive` | Owner `{expected_epoch}`; fence active requests and reject new work; preserve data. |
| `POST /adms/{adm}/snapshot-exports` | Owner idempotent export operation pinned to the accepted revision at receipt. |

A snapshot transport is `{manifest: BASE64, files: {ARTIFACT_PATH: BASE64}}`, carrying exact core snapshot bytes. Exports return this object under `result.snapshot`; place it in a create/import body to clone independently. A public JSON body is limited to **2 MiB**, including base64. Exports are checked and limited so their package fits this import envelope with bounded metadata. This API profile does not claim the core library's larger archive limit, file uploads or streaming archives. The [engine API](ENGINE.md) remains available for larger library-only packages.

Imports recheck finite content, evidence closure, typed state and the actual owner policy. They do not import proof status or operational authority. Exports preserve the source ADM identity as provenance and exclude requests, credentials, attempts, consumers and jobs. Neither operation is an operational backup.

Creation and model-operation idempotency keys are installation-scoped. Request keys are ADM-scoped. Identical validated canonical input returns the same resource; changed input under the same key returns `409`. The shared local HTTP boundary is checked on every replay. Failed operations keep their identity; an explicit new key is needed for a new operation. A committed instance can be reconciled with its operation after restart without creating a duplicate. A failed validation never produces a ready instance.

## Durable local requests

Create `request.json`:

```json
{
  "request_profile":"awm-adm-request/2",
  "engine_profile":"finite-v0",
  "idempotency_key":"inspect-capabilities-1",
  "query":{"op":"capabilities"},
  "limits":{"max_work":100000,"max_duration_ms":5000},
  "on_gap":"report"
}
```

```sh
python3 scripts/api_client.py /api/v1/adms/ADM_UUID/requests --method POST --body request.json
python3 scripts/api_client.py /api/v1/adms/ADM_UUID/requests/REQUEST_UUID
```

An optional `If-Match` header contains the exact revision UUID displayed by the client (this bounded API profile accepts one bare ID, not HTTP ETag lists or wildcards). A newly submitted request checks it inside the enqueue transaction; mismatch returns `409 stale_context`. A matching idempotent replay returns the original resource before this precondition is evaluated. Clients omitting the header pin the current revision at receipt.

Submission durably commits the normalized envelope, pinned revision/context and `request.received` event, then returns `202`. The scheduler serves at most one request per ADM concurrently, subject to the global compute cap. Request scheduling rotates across ready instances. All computation uses bounded local child processes outside SQLite write transactions; model validation and execution share the same work/time budget. Closing the client leaves the request intact.

The same lifecycle accepts `capabilities`, `evaluate`, `check_claim`, `find_plan`, `check_certificate` and `explain`. The latter accepts a recorded `result_id` from the same ADM; it describes that historical result, preserving its original context. It cannot resolve a result from another instance.

| Status | Meaning |
| --- | --- |
| `received` | Persisted and awaiting local capacity. |
| `evaluating` | A current attempt has a finite lease and is executing. |
| `succeeded` | A checked local result and its event committed together. |
| `inconclusive` | Work/time/process interruption prevented a conclusion. No learning gap is inferred from exhaustion. |
| `needs_input` | Unsupported/missing model content, invalid local query/proof, or changed owner context needs attention. |
| `failed` | An operation/child result could not be safely completed. |
| `cancelled` | Cancellation or archive won publication authority. |

`waiting_for_learning` is emitted only when an explicitly authorized durable episode is attached. The worker claims one bounded acquisition at a time; gateway readiness indicates dispatch capability, not an active call.

Successful results use the AWM-ADM envelope around the unchanged finite result. It binds ADM, request, attempt, theory root, support root, owner epoch, semantic query digest, original selection intent and resolved actions. `module_all` differs from an explicit action list, including an empty list. A replayed witness, shortest action count, bounded no-plan conclusion and unreachability are separate claims. Lean kernel checking and exhaustive finite correspondence remain separate; the interpreter and translator are trusted.

The resource includes both `pinned_context` and `current_context`. Historical results retain their original bindings when mode/requirements change. Installing a policy performs local conformance checks before an expected-epoch commit; concurrent changes reject stale installation. Owner epoch changes fence outstanding requests and cancel their compute children. New work uses the current policy; past answers are not rewritten or promoted to current-policy results.

`POST /requests/{id}/cancel` is idempotent and fences queued/running attempts before stopping their child. Completed outcomes remain unchanged. `POST /requests/{id}/retry` deliberately retries an inconclusive/failed/needs-input local request with a fresh attempt, preserving its most recently pinned revision and original query meaning. A changed owner epoch requires a new request. Restart and expiry reclaim a running attempt as `inconclusive`, retain its attempt record and produce an event; they do not automatically repeat it. Queued requests resume normally after restart. No cancelled, expired or old-generation attempt can publish.

List requests with `after` and `limit` (1–100). Lists return bounded request summaries (without result payloads) and an optional `next_cursor`; retrieve an individual request for its result and attempt history. Requests, attempts, operations and revisions have finite retention caps and SQLite/storage limits. Hitting a cap rejects additional work explicitly; automatic request deletion or idempotency expiry is not implemented. Retained-attempt capacity is four times the configured request-count limit, shared by the ADM.

## Durable events and independent consumers

```sh
python3 scripts/api_client.py '/api/v1/adms/ADM_UUID/events?after=0&limit=50'
python3 scripts/api_client.py /api/v1/adms/ADM_UUID/events --events
```

Polling and SSE read the same transactional outbox. Polling returns `items`, `cursor`, `earliest_cursor` and `latest_cursor`. SSE uses stable `ADM_UUID:SEQUENCE` event IDs; reconnect with `Last-Event-ID`. A cursor from another ADM is rejected. Delivery is at least once: deduplicate by event ID. SSE connections are bounded to 15 seconds and 32 simultaneous streams; reconnect normally. `?once=true` returns one current batch for clients/tests. Expired credentials or history gaps during a stream produce a `control` event and close the connection.

`POST /event-consumers` creates a cursor bound to the workspace actor. `PUT /event-consumers/{id}/cursor` advances only that workspace's consumer monotonically. Each ADM retains at most 100 consumers. Acknowledgment does not delete events or affect another consumer.

The owner may explicitly prune an event prefix with `POST /events/prune` and `{cursor:N}`. This affects event delivery history, not requests, results, model versions or idempotency. Lagging cursors receive `410 cursor_expired`; retrieve `/event-window`, reload current resources, and resume at the reported earliest cursor. The owner retention preview reports an eligible age-based event prefix. Automatic deletion and wider evidence garbage collection remain unavailable; see [OPERATIONS.md](OPERATIONS.md). No global order across ADMs is implied.

## Storage, errors and recovery

Schema 3 extends owned schemas 1/2 transactionally with credentials, model operations, immutable revisions, requests, attempts, events and consumers. Existing initialized models and private operator results survive migration. The registry and per-ADM databases retain separate transactions. Creation uses durable intent reconciliation; request outcome and event commit in one ADM transaction. Future schema versions and foreign stores remain rejected. This is one storage owner on a local filesystem, not a multi-replica service.

Errors use `awm-adm-error/2` with a stable code, retry class and bounded application-authored diagnostics. Malformed/duplicate-key/nonfinite/deep/oversized JSON is rejected before business logic. Framework validation does not echo supplied values. Error envelopes omit internal exception strings, credentials and raw provider error bodies. Owner-only learning resources expose bounded structured proposal output and local diagnostics for review, never hidden reasoning or saved credentials.

The [runtime guide](RUNTIME.md) covers Docker limits and shutdown. The [validation register](TESTING.md) records actual checks. Domain content stays in instance data and fixtures; none of these endpoints defines a product-wide domain.

Primary implementation references: [FastAPI security and constant-time comparison](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/), [SQLite transactions](https://www.sqlite.org/lang_transaction.html), and [SSE reconnection and event IDs](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events). The installed Starlette response implementation supplies bounded ASGI streaming; no in-memory-only notification bus is used.

Request and revision lists accept `order=asc` (default) or `order=desc`, rejecting other values. The numeric cursor denotes the last sequence returned; descending pages select lower sequences. Owner requirement reads bind the returned policy and epoch to the same immutable revision.

## Managed learning resources

The [learning API](LEARNING.md#api-resources) retains learning diagnostics, `/dispatches`, per-ADM `/episodes` and candidate review routes alongside the single `/connection` controls. [OpenAPI](../contracts/openapi.json) contains the complete implemented schemas. Provider output cannot change connection settings. Pending requests expose durable learning job IDs; a successful publication may repin a new local attempt only for explicitly authorized learning interests. `initial_revision_id` and each attempt's `revision` preserve historical pins. Interruption never retries an uncertain provider call.

The [language API](LANGUAGE.md#api-resources) adds local/optional external interpretations, explicit confirmation, vocabulary and bounded conversations. Local interpretation accepts scoped submit authority; provider interpretation, vocabulary edits and teaching proposals require owner authority. Interpretation confirmation creates a normal request with the same local result and lifecycle contracts.

## Manual sources and historical facts

The [source guide](SOURCES.md) defines the implemented immutable intake, explicit extraction, owner projection policy, reviewed admission, corrections/support holds and durable `lookup_fact` interface. Source text remains untrusted data. The [feed guide](FEEDS.md) defines implemented standing policies, finite processing reservations, explicit reprocessing, bounded history and coverage transitions. See [release scope](RELEASE.md) for supported capabilities and limits.

## Service operations

`GET /api/v1/operations` returns up to 50 operation summaries without payloads. Optional `since_ms` is an inclusive receipt-time lower bound in Unix milliseconds, applied before the limit; optional `include_deletions=true` combines deletion status with create/export records and sorts newest first by receipt time (operation identity breaks ties). Summaries include `created_at_ms`. Defaults preserve the unfiltered create/export list. The console requests the preceding seven days; older records remain stored and readable by ID. Deletion responses also include `created_at_ms`; `/deletions?scope=active` retains older unfinished operations and their existing explicit retry path. Reading these lists does not advance or retry work.

`GET /api/v1/operations/diagnostics` returns an local report capped at 1 MiB: process timing/work counters, persistent queue/status counts, app-store bytes, provider accounting and retention eligibility. `GET /api/v1/operations/retention` returns the retention preview. Neither includes raw source/model/query/credential content. Metric counters reset at process start; persistent accounting does not.

Service backup and restore use an offline operator CLI, never public API filesystem paths. They require stopped storage owners and a fresh destination. [Operations contract](OPERATIONS.md)

## Provider failures and intake

Connection failures, malformed or incomplete output, transport errors and unknown usage are retained with bounded diagnostics. These do not imply insufficient credit or a free call. A stopped or unavailable connection prevents new provider work; accepted local execution remains independent. No automatic retry is issued for an uncertain call.

[Ask](ASK.md) defines checked interpretation, local result bindings and separately labeled narration. [Intake](INTAKE.md) defines uploads, automatic source checking and append-only producer routes. Exact technical records remain inspectable through local endpoints; the console presents readable outcomes.

## owner model lifecycle

[Model lifecycle](MODEL_LIFECYCLE.md) adds local `PATCH /api/v1/adms/{adm}/name`, `DELETE /api/v1/adms/{adm}` and bounded `/api/v1/deletions` progress/retry routes. Named deletion commits the access/publication fence before cleanup. Existing AWM-ADM model routes subsequently return `410 gone` (revoked credentials fail earlier); export/import operation records no longer expose that model's payload. No provider call is issued by these controls. Snapshot copies and shared connections retain their independent identities.

## Connector revision and admission metadata

Direct Ask/Teach accept an optional `If-Match` revision ID. The connector supplies it on every new submission. The service resolves an identical idempotent replay before testing freshness; stale new work returns `409 stale_context` before provider dispatch. A changed body under an existing identity remains a conflict.

Teach views include typed `admissions`, projected from retained local receipts. Each identifies its objective, receiver sequence, actual status/mode, base and decision revisions, accepted revision, declaration/support effects and checked diagnostics when available. Classifications distinguish `accepted`, `preservation_conflict`, `checked_violation` and `unresolved`. Backward rejection of a replacement is not a proof of logical contradiction. Older receipts may lack added revision/effect metadata; missing values stay null. Both acquisition and source-projection receipts are included, ordered by receiver sequence. Accepted `effects.change_report` compares checked before/after definitions and evidence; `teaching.summary.changes` combines bounded publication reports with receipt/revision references. Preserved dependent definitions are distinct from logical rule changes even if their artifact IDs were replaced. Completeness and abbreviation flags are explicit; no receipt implies every objective succeeded. See [change reporting](CHANGE_REPORTING.md).
