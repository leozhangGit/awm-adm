# Ask, interpretation and local answers

This is the AWM-ADM explicit-preview language contract, retained through the interpretation API. The AWM-ADM [Ask/Teach workspace](CONVERSATIONS.md) has separate conversation/authority records. [Automatic Ask](ASK.md) implements checked read-only execution and optional grounded narration under the enabled connection. The [teaching coordinator](TEACHING_EXECUTION.md) prepares, executes and reports bounded teaching tasks.

The preview service adds a bounded language layer to the local service. It translates a question into a checked `awm-adm-intent/2` preview. Explicit confirmation creates an ordinary local request; the finite engine computes the answer. An interpretation is neither a theory update nor evidence that a provider understood the user correctly.

## Explicit preview API

The normal console uses direct Ask with automatic checked execution. Integrations can still use the explicit preview API: create an interpretation session, submit a local controlled phrase or provider-assisted question, inspect the typed preview, then confirm it with exact revision/catalog bindings. Clarifications have no executable query. Structured request APIs expose all finite operations, including certificates, independently of a remote provider.

The local language is controlled, not unrestricted English. The [grammar and fact profiles](SOURCES.md) define its syntax. Templates supply editable starting values, not a claim that those values represent the user's situation. Qualified symbols are exact; ambiguous aliases return choices. JSON values must match finite carriers. Missing entities, dates, units or state require clarification. This explicit preview grammar performs no implicit date interpretation, extrapolation or unit conversion. Automatic Ask additionally supports [calendar-date historical interpretation](TEMPORAL_INTERPRETATION.md) using the service timezone and checked whole-period lookup.

## Owner vocabulary and catalog

Each ADM has a separately versioned owner vocabulary: symbol/module aliases, function parameter units and roles (`value`, `entity`, `time`), and explicit aliases for finite parameter values. The vocabulary API edits this metadata. Targets and values must exist in the current accepted model; aliases cannot override exact symbols or reinterpret an already valid literal. Unit-bearing parameters require `{"value": VALUE, "unit": "EXACT_UNIT"}`. Time parameters use the finite type chosen by the model, such as a bounded year integer or date enum; receipt time and “now” are never substituted.

The catalog contains accepted signatures, types, modules, state/action interfaces and owner vocabulary. It excludes function/transition bodies and evidence. Catalog encoding is canonical and bounded to 256 KiB. Its digest binds every preview, alongside ADM identity, theory/support roots, mode/policy epoch, immutable application revision and vocabulary generation.

Vocabulary is local service metadata. It is not part of a portable model snapshot and does not alter finite artifacts or conformance policy. After a theory change, catalog/Ask/Teach reads derive a validated compatible view at the pinned revision while preserving the stored profile and generation. Obsolete targets, parameter names and invalid value aliases are omitted; valid entries remain. If any target of an ambiguous alias disappears, the whole alias is omitted, never silently narrowed or retargeted. Explicit vocabulary installation remains strict. Computation exhaustion is not interpreted as obsolete metadata. Snapshot restoration starts with empty vocabulary. Conversations and teaching proposals likewise remain local service history, not model knowledge or snapshot content.

## Explicit provider interpretation

The single enabled connection supplies provider interpretation. Explicit preview clients bind its current version and select bounded disclosure. Direct Ask selects bounded prior owner context automatically. The payload contains the question, accepted catalog/vocabulary and eligible owner messages, plus bounded result identifiers where needed. It excludes credentials, other models, assistant prose and unrestricted evidence. Recorded adapters use the same contract without network calls.

The provider receives a model-neutral schema with `status`, one controlled-language `command`, `assumptions` and `clarification`. It does not supply an `IntentDraft`, revision binding, approval or answer. The application parses and type-checks the proposed command locally and constructs the draft. Unsupported/admin commands, invented symbols, malformed replies and extra authority fields cannot produce an executable preview. A wrong but well-typed interpretation can still pass these checks: explicit preview clients can review its meaning before confirmation; direct Ask uses the checked interpretation automatically.

One interpretation reserves at most one call under its explicit call limits and configured concurrency. It does not start a learning episode. The gateway owns credentials, egress and at-most-once dispatch. Refusal, timeout, stale authority, resource exhaustion or malformed output ends the interpretation; no automatic repair, fallback provider, model change or larger budget follows. Unknown dispatched usage remains reserved across restart. Provenance records requested/returned models and prompt/schema/wire identities. Simulated adapters and recorded trials do not establish live model translation accuracy.

## Lifecycle, confirmation and bounded history

Interpretations progress from `queued` to a terminal local outcome or `awaiting_provider`, then `ready`, `needs_clarification`, `unsupported`, `needs_learning` or `failed`. Cancellation is explicit. A gap status does not authorize acquisition. Restart fails unfinished interpretations and preserves known history and uncertain reservations; it never redispatches an uncertain call. Durable queuing does not imply that a worker is active.

Confirmation supplies the interpretation ID, expected revision, catalog digest, request limits and idempotency key. A bounded local recheck precedes an atomic transaction linking consent to one normal request. The transaction checks current revision, vocabulary and cancellation state again. Concurrent/replayed confirmation returns the original request. Cancelling an interpretation after execution does not cancel that separately owned request; use its request controls.

A changed revision or vocabulary makes a preview stale. **Revalidate locally** reparses the original proposed command against the current catalog and compares typed meaning. If the operation/arguments/action scope change, it asks for clarification. Otherwise it creates a new preview requiring new confirmation. No historical decision or result is rewritten, and revalidation does not make another provider call. Historical queries can be inspected through their result bindings; the language execute route does not silently execute an old preview against a new model.

Per ADM: at most 100 conversations; at most 100 combined interpretation/teaching turns per conversation; 16,384 characters per utterance; six/16 KiB selected context turns; one MiB per retained interpretation, including reserved terminal-state headroom. Non-failed/non-cancelled records reserve 1 KiB so a byte-limit failure can still become a durable failed/cancelled record. Configured queue item/byte and storage limits apply as well. History lists compact turn summaries; full details are fetched separately. The language explanation catalog covers the latest 100 successful result IDs; the structured interface can inspect older retained results. Background interpretation shares bounded checking capacity with learning; local serving has separate capacity. Each check also consumes the configured finite work/time/memory budget.

## Provider failure diagnostics

Provider-assisted interpretation failures retain specific dispatch errors and safe diagnostics in `provider_failure`. Ask displays supported incomplete reasons and unsettled token reservations, including an explicit warning for remote zero/zero reports. Older generic failures are explained from their retained dispatch without rewriting the conversation or inventing a missing reason. The [shared learning contract](LEARNING.md) governs diagnostics and usage; no diagnostic view reissues a provider request.

## Teach and acquisition

The legacy interpretation-session Teach endpoint saves an unaccepted teaching draft only. It does not publish or acquire. Normal direct Teach at `/adms/{adm}/teach` prepares and executes a checked task automatically; see [Teaching](TEACHING.md). Both routes preserve the distinction between user intent, proposed representation and accepted theory.

## API resources

All routes use `/api/v1/adms/{adm}` and the existing strict JSON and local-access boundaries. `interpretation-sessions` groups manual previews and teaching drafts; it is separate from the Ask/Teach `conversations` resource. Session identifiers still occupy the existing `conversation_id` payload field.

| Route | Authority and behavior |
| --- | --- |
| `GET /language/catalog` | Read; bounded current accepted catalog and digest. |
| `GET`, `PUT /language/vocabulary` | Read; owner update with `expected_revision` and `expected_generation`. |
| `GET`, `POST /interpretation-sessions` | List; submit creates an idempotent titled interpretation session. |
| `GET /interpretation-sessions/{id}` | Read compact interpretation summaries and teaching drafts. |
| `POST /interpretation-sessions/{id}/teach` | Owner; save a teaching proposal only. |
| `POST /interpretations` | Submit for local; owner for external. Requires conversation, utterance, expected revision and idempotency key. |
| `GET /interpretations/{id}` | Read draft, stale status, provenance, usage and linked local request. |
| `POST /interpretations/{id}/clarify` | Create a new immutable turn with a complete replacement utterance under the same authorization rules. |
| `POST /interpretations/{id}/revalidate` | Submit; create a locally rechecked preview at an expected current revision. |
| `POST /interpretations/{id}/execute` | Submit; explicit confirmation with revision, catalog digest, limits and idempotency key. |
| `POST /interpretations/{id}/cancel` | Submit; fence later interpretation completion/execution. |

Vocabulary, interpretation, execution and teaching events are durable per-ADM records under owned schema 19. Supported migrations preserve existing model revisions, requests, learning receipts and finite encodings. [OpenAPI](../contracts/openapi.json) describes exact inputs; [API](API.md) and [learning](LEARNING.md) define their authority and recovery contracts.
