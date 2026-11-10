# Authenticated local application API

The service exposes model, learning, source, administrator, spending and conversational resources under `/api/v1` within AWM-ADM 0.3.0. See [administrator access](ADMINISTRATOR.md), [priced allowances](PRICED_ALLOWANCES.md), [conversations](CONVERSATIONS.md) and [OpenAPI](../contracts/openapi.json).

The public API runs at `http://127.0.0.1:8080/api/v1`. It exposes independent ADM initialization, durable local requests, exact result bindings, owner settings/requirements, bounded model operations and retained events. The [browser console](CONSOLE.md) uses these same routes for owner workflows. [Bounded learning and provider dispatch](LEARNING.md) use separate owner-authorized resources. A gap alone does not create a provider grant: an explicit episode can attach eligible requests, retain their learning interests, and trigger a new local attempt after checked publication. Provider output is never substituted for a request result.

## Resource names and versioning

| Resource | Purpose |
| --- | --- |
| `/adms/{adm}/conversations` | Durable Ask/Teach chats, turns, setup and decisions |
| `/adms/{adm}/interpretation-sessions` | Manual preview history and unaccepted teaching drafts in Local debug |
| `/adms/{adm}/interpretations` | Individual interpreted requests, clarification and explicit local execution |
| `POST /adms` | Create an empty model or import a snapshot supplied in the body |
| `/adms/{adm}/attachments` | Upload and list retained material with actual stored content |
| `/auth/login`, `/auth/me`, `/auth/logout` | Administrator password sessions |
| `/auth/tokens` | Issue/revoke scoped programmatic credentials |

The public service has no `/api/v2` or `/api/v3` aliases or redirects. The session-bootstrap, metadata-only attachment and duplicate snapshot-import endpoints are not exposed. Clients must use the paths above. Existing serialized profile identifiers, database schema 15 and snapshot encodings are independent of URL versions and remain unchanged. Health checks stay at `/health/live` and `/health/ready`; private operator/worker routes are separate from the public API.

## Historical lookup and preparation renewal

Under `/api/v1/adms/{adm}`, `GET /history-options` returns revision-bound metadata for accepted historical lookup, including independently imported snapshots. It exposes no source-intake permission and requires scoped read authority. Owner-only `GET /tasks/{task}/renewal` previews a bounded unchanged-preparation time extension; `POST` confirms its exact retained task, allowance and configuration bindings. It changes no cap or consumed usage, starts no execution and uses a durable recovery journal. See [execution](TEACHING_EXECUTION.md).

Conversation reads expose typed readiness issues for remote access, connection purpose, supported pricing and allowance state. Message submission rechecks these before creating work. Browser drafts survive tab-local reload/navigation; credentials are never stored with them. Existing local requests remain available through the `/api/v1` API without remote interpretation.

## Start and authenticate

[Administrator authentication](ADMINISTRATOR.md) uses `/api/v1/auth`. Establish the local administrator once and use email/password for owner access. Fresh stores require setup; ordinary updates preserve compatible runtime data.

The standard-library client keeps credentials in memory and prompts securely for a one-command administrator session:

```sh
python3 scripts/api_client.py /api/v1/adms --login
python3 scripts/api_client.py /api/v1/openapi.json --login > openapi.json
```

Use `--token-file /private/path/client-token` for an explicitly issued scoped client. Password login, session cookies and CSRF authorize owner operations; the old owner bearer stops working publicly after account setup. The private operator credential remains available for local recovery.

Resource reads/mutations require authentication. Static assets, minimal health/system data and the setup-required boolean remain public on loopback. The owner-authenticated OpenAPI export describes this unified API. No provider secret or owner credential is embedded in the assets.

Owners issue expiring scoped clients through `POST /api/v1/auth/tokens`, with explicit `adms` and `permissions: ["read", "submit"]`. Read covers inspection/events; submit covers local request submission/cancellation/retry. These clients cannot manage models/policies, issue credentials, administer accounts or inspect owner operations. Existing scoped clients retain their scopes after administrator setup/password changes. They expire or may be explicitly revoked; whole-service restore deliberately revokes them. At most 256 active credentials are retained.

The administrator cookie is HttpOnly, SameSite=Strict and scoped to `/api`. Mutations require `X-CSRF-Token`. Sessions expire after eight hours, survive ordinary restart, and are revoked on logout/password change/recovery as documented in the [account guide](ADMINISTRATOR.md). The local HTTP profile does not mark cookies Secure; off-host/reverse-proxy deployment is unsupported. All `/api/v1` routes enforce Host/Origin, JSON-only input, body limits and cross-site mutation rejection.

## Instances and model operations

Create `create.json`:

```json
{"idempotency_key":"my-first-adm","name":"My first ADM","mode":"backward"}
```

```sh
python3 scripts/api_client.py /api/v1/adms --method POST --body create.json --login
python3 scripts/api_client.py /api/v1/operations/OPERATION_UUID --login
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

Creation and model-operation idempotency keys are installation-scoped. Request keys are ADM-scoped. Identical validated canonical input returns the same resource; changed input under the same key returns `409`. Authorization is rechecked on every replay. Failed operations keep their identity; an explicit new key is needed for a new operation. A committed instance can be reconciled with its operation after restart without creating a duplicate. A failed validation never produces a ready instance.

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
python3 scripts/api_client.py /api/v1/adms/ADM_UUID/requests --method POST --body request.json --login
python3 scripts/api_client.py /api/v1/adms/ADM_UUID/requests/REQUEST_UUID --login
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
python3 scripts/api_client.py '/api/v1/adms/ADM_UUID/events?after=0&limit=50' --login
python3 scripts/api_client.py /api/v1/adms/ADM_UUID/events --events --login
```

Polling and SSE read the same transactional outbox. Polling returns `items`, `cursor`, `earliest_cursor` and `latest_cursor`. SSE uses stable `ADM_UUID:SEQUENCE` event IDs; reconnect with `Last-Event-ID`. A cursor from another ADM is rejected. Delivery is at least once: deduplicate by event ID. SSE connections are bounded to 15 seconds and 32 simultaneous streams; reconnect normally. `?once=true` returns one current batch for clients/tests. Expired credentials or history gaps during a stream produce a `control` event and close the connection.

`POST /event-consumers` creates a cursor bound to the authenticated principal. `PUT /event-consumers/{id}/cursor` advances only that principal's consumer monotonically. Each ADM retains at most 100 consumers. Acknowledgment does not delete events or affect another consumer.

The owner may explicitly prune an event prefix with `POST /events/prune` and `{cursor:N}`. This affects event delivery history, not requests, results, model versions or idempotency. Lagging cursors receive `410 cursor_expired`; retrieve `/event-window`, reload current resources, and resume at the reported earliest cursor. The owner retention preview reports an eligible age-based event prefix. Automatic deletion and wider evidence garbage collection remain unavailable; see [OPERATIONS.md](OPERATIONS.md). No global order across ADMs is implied.

## Storage, errors and recovery

Schema 3 extends owned schemas 1/2 transactionally with credentials, model operations, immutable revisions, requests, attempts, events and consumers. Existing initialized models and private operator results survive migration. The registry and per-ADM databases retain separate transactions. Creation uses durable intent reconciliation; request outcome and event commit in one ADM transaction. Future schema versions and foreign stores remain rejected. This is one storage owner on a local filesystem, not a multi-replica service.

Errors use `awm-adm-error/2` with a stable code, retry class and bounded application-authored diagnostics. Malformed/duplicate-key/nonfinite/deep/oversized JSON is rejected before business logic. Framework validation does not echo supplied values. Error envelopes omit internal exception strings, credentials and raw provider error bodies. Owner-only learning resources expose bounded structured proposal output and local diagnostics for review, never hidden reasoning or saved credentials.

The [runtime guide](RUNTIME.md) covers Docker limits and shutdown. The [validation register](TESTING.md) records actual checks. Domain content stays in instance data and fixtures; none of these endpoints defines a product-wide domain.

Primary implementation references: [FastAPI security and constant-time comparison](https://fastapi.tiangolo.com/advanced/security/http-basic-auth/), [SQLite transactions](https://www.sqlite.org/lang_transaction.html), and [SSE reconnection and event IDs](https://developer.mozilla.org/en-US/docs/Web/API/Server-sent_events/Using_server-sent_events). The installed Starlette response implementation supplies bounded ASGI streaming; no in-memory-only notification bus is used.

Request and revision lists accept `order=asc` (default) or `order=desc`, rejecting other values. The numeric cursor denotes the last sequence returned; descending pages select lower sequences. Owner requirement reads bind the returned policy and epoch to the same immutable revision.

## Managed learning resources

The [learning API](LEARNING.md#api-resources) adds owner-only `/learning`, `/connections`, `/dispatches`, per-ADM `/episodes` and candidate review routes. [OpenAPI](../contracts/openapi.json) contains the complete implemented schemas. No scoped request token can grant provider authority. Pending requests expose durable learning job IDs; a successful publication may repin a new local attempt only for explicitly authorized learning interests. `initial_revision_id` and each attempt's `revision` preserve historical pins. Interruption never retries an uncertain provider call.

The [language API](LANGUAGE.md#api-resources) adds local/optional external interpretations, explicit confirmation, vocabulary and bounded conversations. Local interpretation accepts scoped submit authority; provider interpretation, vocabulary edits and teaching proposals require owner authority. Interpretation confirmation creates a normal request with the same local result and lifecycle contracts.

## Manual sources and historical facts

The [source guide](SOURCES.md) defines the implemented immutable intake, explicit extraction, owner projection policy, reviewed admission, corrections/support holds and durable `lookup_fact` interface. Source text remains untrusted data. The [feed guide](FEEDS.md) defines implemented standing policies, lifetime allowances, explicit reprocessing, bounded history and coverage transitions. See [release scope](RELEASE.md) for supported capabilities and limits.

## Service operations

`GET /api/v1/operations/diagnostics` returns an owner-only report capped at 1 MiB: process timing/work counters, persistent queue/status counts, app-store bytes, provider accounting and retention eligibility. `GET /api/v1/operations/retention` returns the retention preview. Instance-scoped tokens cannot access either endpoint. Neither includes raw source/model/query/credential content. Metric counters reset at process start; persistent accounting does not.

Service backup and restore use an offline operator CLI, never public API filesystem paths. They require stopped storage owners and a fresh destination. [Operations contract](OPERATIONS.md)

## Provider error detail

The service returns HTTP 403 with code `remote_calls_disabled` when a ready, otherwise-authorized remote connection is blocked by the installation allowance. The message points the owner to Connections. Generic permission failures remain `forbidden`; neither response authorizes retries, enables calls or proves a provider key/model works. Generated error schemas include this code.

## Ask

[Ask contracts](ASK.md) add explicit `purpose=ask` interaction options/setup, optional `narrate_results`, immutable `GET /api/v1/adms/{adm}/presentations/{id}` and idempotent `POST /api/v1/adms/{adm}/ask/{work}/teach`. All are owner-only. A confirmed Ask setup permits automatic checked read-only local execution; AWM-ADM preview/execution semantics are unchanged. The generated OpenAPI records the closed setup and gap inputs.

## managed intake

[INTAKE.md](INTAKE.md) defines the implemented owner upload and append-only producer routes, exact disclosure/start authority, shared parent accounting and refusal/replay semantics. [OpenAPI](../contracts/openapi.json) includes `Upload`, `AppendInput`, `AppendCredential`, optional message/setup flags and the `finish` task command. The receipt lookup path uses the original producer idempotency key.

## owner model lifecycle

[Model lifecycle](MODEL_LIFECYCLE.md) adds owner-only `PATCH /api/v1/adms/{adm}/name`, `DELETE /api/v1/adms/{adm}` and bounded `/api/v1/deletions` progress/retry routes. Named deletion commits the access/publication fence before cleanup. Existing AWM-ADM model routes subsequently return `410 gone` (revoked credentials fail earlier); export/import operation records no longer expose that model's payload. No provider call is issued by these controls. Snapshot copies and shared connections retain their independent identities.
