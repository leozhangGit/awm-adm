# Ask, interpretation and local answers

This is the AWM-ADM explicit-preview language contract, retained under **Local debug → Interpretation preview**. The AWM-ADM [Ask/Teach workspace](CONVERSATIONS.md) has separate conversation/authority records. [Automatic Ask](ASK.md) implements checked read-only execution and optional grounded narration under explicit interaction setup. The [teaching coordinator](TEACHING_EXECUTION.md) prepares, executes and reports bounded teaching tasks.

The preview service adds a bounded language layer to the local service. It translates a question into a checked `awm-adm-intent/2` preview. Explicit confirmation creates an ordinary local request; the finite engine computes the answer. An interpretation is neither a theory update nor evidence that a provider understood the user correctly.

## Console workflow

1. Open a model's **Playground → Ask / Teach**, select or create a conversation, and choose **Ask**.
2. Use **Local phrases from this model** for editable templates. Local interpretation needs no provider or network. **Guided / JSON** remains available for all structured operations, including certificates.
3. Choose **Interpret and preview**. Inspect the operation, arguments, initial state, action selection, depth, revision and assumptions. A clarification response has no executable query; supply a complete replacement question and select **Submit clarification**.
4. Select **Confirm and run locally**. The resulting value, plan or explanation comes from the existing local request/result service. Provider prose is never displayed as an authoritative answer. Request history retains its attempt and revision bindings.

The local language is controlled, not unrestricted English. The [grammar and fact profiles](SOURCES.md) define its syntax. Templates supply editable starting values, not a claim that those values represent the user's situation. Qualified symbols are exact; ambiguous aliases return choices. JSON values must match finite carriers. Missing entities, dates, units or state require clarification. No implicit date interpretation, extrapolation or unit conversion occurs.

## Owner vocabulary and catalog

Each ADM has a separately versioned owner vocabulary: symbol/module aliases, function parameter units and roles (`value`, `entity`, `time`), and explicit aliases for finite parameter values. **Owner vocabulary** in the playground edits this metadata. Targets and values must exist in the current accepted model; aliases cannot override exact symbols or reinterpret an already valid literal. Unit-bearing parameters require `{"value": VALUE, "unit": "EXACT_UNIT"}`. Time parameters use the finite type chosen by the model, such as a bounded year integer or date enum; receipt time and “now” are never substituted.

The catalog contains accepted signatures, types, modules, state/action interfaces and owner vocabulary. It excludes function/transition bodies and evidence. Catalog encoding is canonical and bounded to 256 KiB. Its digest binds every preview, alongside ADM identity, theory/support roots, mode/policy epoch, immutable application revision and vocabulary generation.

Vocabulary is local service metadata. It is not part of a portable model snapshot and does not alter finite artifacts or conformance policy. After a theory change, stale vocabulary may require an owner update before interpretation resumes. Snapshot restoration starts with empty vocabulary. Conversations and teaching proposals likewise remain local service history, not model knowledge or snapshot content.

## Explicit provider interpretation

The owner enables the **interpretation** purpose on a versioned connection and selects it for one question. Existing connections keep their existing purposes; an upgrade does not silently authorize translation. OpenAI/Anthropic calls additionally require the global remote-call setting. Recorded connections exercise the same dispatch path without a network provider.

Before each submission, the console asks permission to disclose the question, accepted catalog, owner vocabulary and explicitly selected prior **user** messages. Only selected messages from the same conversation and ADM are eligible. A bounded list of recorded local result IDs is also included to resolve explanations; result values, assistant prose, evidence and credentials are not included. Selected history is capped at six turns and 16 KiB of encoded context. There is no automatic conversation summarization or assistant-answer reuse.

The provider receives a model-neutral schema with `status`, one controlled-language `command`, `assumptions` and `clarification`. It does not supply an `IntentDraft`, revision binding, approval or answer. The application parses and type-checks the proposed command locally and constructs the draft. Unsupported/admin commands, invented symbols, malformed replies and extra authority fields cannot produce an executable preview. A wrong but well-typed interpretation can still pass these checks: the UI labels it as provider-proposed and requires review of its meaning.

One interpretation reserves at most one call under its explicit call limits and the shared connection/ADM/installation quotas. It does not start a learning episode. The gateway owns credentials, egress and at-most-once dispatch. Refusal, timeout, stale authority, quota exhaustion or malformed output ends the interpretation; no automatic repair, fallback provider, model change or larger budget follows. Unknown dispatched usage remains reserved across restart. Provenance records requested/returned models and prompt/schema/wire identities. Simulated adapters and recorded trials do not establish live model translation accuracy.

## Lifecycle, confirmation and bounded history

Interpretations progress from `queued` to a terminal local outcome or `awaiting_provider`, then `ready`, `needs_clarification`, `unsupported`, `needs_learning` or `failed`. Cancellation is explicit. A gap status does not authorize acquisition. Restart fails unfinished interpretations and preserves known history and uncertain reservations; it never redispatches an uncertain call. Durable queuing does not imply that a worker is active.

Confirmation supplies the interpretation ID, expected revision, catalog digest, request limits and idempotency key. A bounded local recheck precedes an atomic transaction linking consent to one normal request. The transaction checks current revision, vocabulary and cancellation state again. Concurrent/replayed confirmation returns the original request. Cancelling an interpretation after execution does not cancel that separately owned request; use its request controls.

A changed revision or vocabulary makes a preview stale. **Revalidate locally** reparses the original proposed command against the current catalog and compares typed meaning. If the operation/arguments/action scope change, it asks for clarification. Otherwise it creates a new preview requiring new confirmation. No historical decision or result is rewritten, and revalidation does not make another provider call. Historical queries can be inspected through their result bindings; the language execute route does not silently execute an old preview against a new model.

Per ADM: at most 100 conversations; at most 100 combined interpretation/teaching turns per conversation; 16,384 characters per utterance; six/16 KiB selected context turns; one MiB per retained interpretation, including reserved terminal-state headroom. Non-failed/non-cancelled records reserve 1 KiB so a byte-limit failure can still become a durable failed/cancelled record. Configured queue item/byte and storage limits apply as well. History lists compact turn summaries; full details are fetched separately. The language explanation catalog covers the latest 100 successful result IDs; the structured interface can inspect older retained results. Background interpretation shares bounded checking capacity with learning; local serving has separate capacity. Each check also consumes the configured finite work/time/memory budget.

## Provider failure diagnostics

Provider-assisted interpretation failures retain specific dispatch errors and safe diagnostics in `provider_failure`. Ask displays supported incomplete reasons and unsettled token reservations, including an explicit warning for remote zero/zero reports. Older generic failures are explained from their retained dispatch without rewriting the conversation or inventing a missing reason. The [shared learning contract](LEARNING.md) governs diagnostics and usage; no diagnostic view reissues a provider request.

## Teach and acquisition

**Teach** saves an immutable, idempotent teaching draft with text and revision, marked unaccepted and without publication authority. **Review learning task** transfers its text into the Learning task editor. The owner must define receiver-owned interfaces and an acquisition contract, choose a connection and budgets, and approve disclosure before starting the separate learning episode. The regular admission and forward/backward rules still apply. Long source text may need a smaller task description; it is never silently truncated into a learned fact. Source/span extraction and historical fact projection are source work.

## API resources

All routes use `/api/v1/adms/{adm}` and the existing strict JSON/authentication boundaries. `interpretation-sessions` groups manual previews and teaching drafts; it is separate from the Ask/Teach `conversations` resource. Session identifiers still occupy the existing `conversation_id` payload field.

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

Vocabulary, interpretation, execution and teaching events are durable per-ADM events. SQLite schema 5 adds owned history tables transactionally without rewriting existing model revisions, requests, learning receipts or finite encodings. [OpenAPI](../contracts/openapi.json) describes exact inputs; [API](API.md) and [learning](LEARNING.md) retain their authority and recovery contracts.
