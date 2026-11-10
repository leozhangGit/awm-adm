# Ask and Teach workspace

The workspace provides separate durable Ask and Teach channels, bounded clarification, checked teaching preparation/execution and managed source intake. [Ask](ASK.md) describes automatic read-only execution; [Teach](TEACHING.md) and [execution](TEACHING_EXECUTION.md) describe learning authority. Current owned schema is 15.

## What the owner can do

The console opens on the model collection. Create an empty model, import a checked snapshot or export a model through the existing lifecycle. Each model has independent **Ask** and **Teach** histories. Start a conversation or reopen it by its URL/history entry. Messages and pending questions survive reload and application restart. A saved teaching intention is not an accepted rule or a running learning task.

**Set up interaction** in Ask and **Set up teaching task** in Teach offer enabled connections with a current audited price. Teach uses a task-scoped `task_preparation` allowance; legacy clarification consent remains narrow. Ask uses `ask_interpretation` with separately optional `ask_narration`. Secure keys stay in Connections; they must never be entered in chat. An exact USD cap is collected in a local setup exchange because there is no funded LLM authority before the first allowance. Ranges, approximations and generic “yes” replies trigger a bounded follow-up rather than being interpreted as amounts. This narrow parser is an administrative bootstrap, not a substitute for LLM understanding.

The resulting proposal names the provider/model, conversation, purpose, expiry, disclosure and limits. Confirming the specific proposal allocates an interaction allowance for Ask/legacy clarification or a learning-lane task allowance for Teach, and saves the exact preference. It does not call the provider or refill/close a previous allowance. A later ordinary message requests the authorized interaction: checked teaching preparation or Ask interpretation followed by checked read-only local execution and optional narration. Preparation stops at a reviewed specification; acquisition/execution requires the subsequent language contract within the task allowance. Selecting a connection never changes its model or relaxes its price profile.

Installation spending, rates and count-bound profiles remain owner-managed in Connections → Installation spending / Review pricing, or through the [financial API](PRICED_ALLOWANCES.md); arbitrary model pricing is not inferred. When no supported price or enabled connection exists, the UI explains why setup is unavailable. No provider fallback or free setup call occurs. Existing clarification-only preferences stay unchanged. Ask requires its own setup and result-disclosure decision; Teach requires its own task setup as specified in [TEACHING.md](TEACHING.md).

Main messages use readable text with emphasis and inline code. HTML, images, links and embedded content remain inert text. **Details** exposes saved contexts, decisions, questions, usage and work references in one action. **Local debug** retains Interpretation previews and structured local execution; **Advanced model tools** retains Sources/Learning. A AWM-ADM result, request, episode or teaching draft can be linked through the AWM-ADM reference API without inheriting its consent or disclosing it to a provider.

## Ownership and binding

`conversations/service.py` owns the operation allowlist. Legacy clarification-only replies have only `kind = clarification | unavailable` and bounded text. They cannot supply a query, learning contract, cap, authenticated principal, decision or publication request. Teach preparation uses the closed plan and local header/source checks in [Teaching](TEACHING.md). Ask interpretation and narration use the separate checked contracts in [Ask](ASK.md); the display states actual availability independently of provider prose. Shape checking and that label do not prove the provider's prose correct.

Every immutable turn records its server-assigned identity, ADM-owned conversation, channel, author, increasing local sequence, UTC milliseconds, text, attachment metadata references and exact context. Context includes the revision, theory root, evidence-support root, owner epoch, vocabulary generation and source-policy generation. Stored JSON key order is immaterial to equality. Existing finite-model encodings and result bindings are unchanged.

Owner inputs have ADM-scoped idempotency keys and a canonical payload digest. Same key and same payload returns the existing identity, including after restart. Different content or a different conversation conflicts. The browser keeps an unacknowledged submission in tab-local session storage and only retries it through **Recover submission**, using the original body/key. It never resubmits on reload or poll. This outbox contains owner text/context, not credentials; closing the tab may remove the local outbox, while accepted server history remains.

A clarification has an exact question identity, originating turn, context, depth and ten-minute expiry. `reply_to` must name the pending question in this conversation. Old, cross-conversation, missing and mismatched replies cannot enact authority. Each exchange permits four clarification questions. A model/context change fences publication and dispatch of pending work. A new account/password generation also fences unfinished work and pending authority proposals.

A funding decision binds the retained proposal artifact and its digest, current model context, connection price identity, installation spending generation and account generation. The server obtains the principal from authentication. Decisions are accepted, declined or stale; unstructured text is never a decision. Expired proposals remain in Details but can be replaced through fresh setup. Retained links preserve original AWM-ADM identities/bindings; they do not turn a historical answer into a current one.

## Provider context and work

For legacy clarification and Ask, only the current owner message, the exact pending question and up to six owner turns from this same conversation and identical model context are eligible for disclosure. Selected history is bounded to 16 KiB of its canonical encoded representation; JSON escaping can make this stricter than the raw UTF-8 text length. Selection is persisted before dispatch. Assistant history, other Ask/Teach conversations, source/attachment contents and credentials are excluded. Ask additionally discloses the accepted catalog/vocabulary, and separately authorized narration discloses a bounded result packet; see [Ask](ASK.md). Historical links and attachment metadata confer no evidence or disclosure authority.

One conversation has at most one active exchange. The coordinator records `queued` before reserving a purpose-classified child and grant through the existing [runtime ledger](PRICED_ALLOWANCES.md). Its grant binds the exact wire digest, allowance, conversation work identity, revision and authority generations. The provider worker/gateway retain at-most-once dispatch. `queued` or a ready grant is never called “working”; the UI derives working status from an actual lease/dispatch. Completion and its event commit with the retained assistant/system turns in the same ADM transaction.

Legacy clarification and Ask calls use model-neutral instructions/schema, 4,096 output tokens, 60 seconds per call and a five-minute exchange deadline. The allowance lasts at most one hour, has at most six calls, 192,000 aggregate reserved input tokens and 49,152 aggregate output tokens. The verified input bound comes from the installed price, not a wire-byte estimate. Dollar, token, call, child, installation and lane limits can stop earlier. Rejected, incomplete and malformed replies do not yield partial executable output. Safe failure codes and original grant diagnostics are retained in Details. No automatic retry occurs.

Teach has the separate 15-minute task allowance, four-input/24-KiB scope, 8,192-output-token calls and bounded local checks described in [TEACHING.md](TEACHING.md). It discloses accepted headers, installed requirements and source-policy metadata, plus explicitly supplied Teach text, while keeping stored source bodies private.

Restart stops unfinished provider work and preserves its history; already-submitted Ask requests retain their documented local recovery behavior. Existing learning recovery reconciles undispatched and uncertain grants under its original rules; unknown usage stays reserved. A late settlement can update accounting but cannot revive stopped work. Ready clarification questions and completed records persist; expired questions need fresh setup or a new conversation.

## Storage, limits and recovery

Schema 10 adds per-ADM `chat_conversations`, `chat_turns`, `chat_inputs`, `chat_questions`, `chat_proposals`, `chat_decisions`, `chat_work` and `chat_attachments`. explicit-preview language/conversation tables remain untouched. Schema 11 adds immutable `chat_presentations`. The registry upgrade journal reconciles all stores to schema 15; all registered instances must reconcile before dispatch starts. Snapshots still contain accepted model knowledge and requirements, not conversation, account or financial authority.

Conversation creation and owner input/response records commit transactionally. Allowance allocation crosses the ADM and registry stores, so the service first persists an `applying` decision intent. The registry allocation uses an immutable decision-derived key; replay after a crash reuses the allocation. Only a still-current decision installs preferences. A stranded allocation remains accounted for and visible in the ledger; it is never automatically refunded or granted new authority. Terminal decision records are immutable.

Bounds include 100 conversations/model, fewer than 200 turns/conversation with terminal headroom, 1 MiB encoded turn history/conversation, the configured retained-input limit (default 1,000/model), 16 KiB UTF-8/input, four attachment references/input, 400 metadata records/model, 100 historical links/conversation and 20/100 default/maximum page sizes. Each reference/turn also consumes installation storage capacity. Metadata registration accepts only bounded text/Markdown name, byte count and content digest; `content_stored=false` is explicit. It is not an upload endpoint and no file contents are claimed to have been read.

Paired backup/restore supports schema 7 through 15. Restore disables financial/remote authority and revokes account sessions as before. Conversations, original results and uncertain provider accounting remain available without permitting automatic redispatch. Never open a migrated store with an older binary; rehearse using fresh paths and retain the compatible backup.

## API surface

All routes below are owner-only under `/api/v1`. Scoped read/submit credentials do not authorize chat or spending. Same-origin, session CSRF, strict bounded decoding and closed input models apply.

| Route | Meaning |
| --- | --- |
| `GET/POST /adms/{adm}/conversations` | Channel-filtered cursor page / idempotent creation |
| `GET /adms/{adm}/conversations/{id}` | Bounded turns, current context, pending questions/proposals and work summaries |
| `GET /adms/{adm}/conversations/{id}/details` | Bounded full conversation evidence, references and safe provider accounting |
| `GET /adms/{adm}/interaction-options` | Current usable priced clarification/Ask/Teach choices, no dispatch |
| `POST /adms/{adm}/conversations/{id}/setup` | Owner-selected provider/price and current context; asks for an exact cap locally |
| `POST /adms/{adm}/conversations/{id}/messages` | Immutable owner turn; optional exact `reply_to`; durable queued work when funded |
| `POST /adms/{adm}/decisions/{proposal}` | Exact accept/decline with idempotency, payload digest and context |
| `POST /adms/{adm}/conversations/{id}/links` | Typed reference to an existing same-ADM AWM-ADM request/result/episode/teaching draft |
| `GET/POST /adms/{adm}/attachments` | List retained material / upload immutable content under intake limits |

Operational views expose retained payloads, status projections and exact references. The runtime input adds optional `reply_to` to the message contract; default byte/count limits are narrower than the specification hard ceilings. [Generated OpenAPI](../contracts/openapi.json) describes implemented inputs. `conversation.turn`, `.queued`, `.completed` and `.decision` events reuse the durable AWM-ADM event transport and independent consumer cursors. Browser polling only reads these durable resources; it does not drive or restart work.

Ask execution, presentation recovery, schema-11 migration and the additional owner-only routes are specified in [ASK.md](ASK.md). Existing clarification and AWM-ADM reference semantics retain their original scope.

Teaching tasks use separate learning-lane setup, bounded conversational clarification and a checked, uninstalled specification. See [TEACHING.md](TEACHING.md) for the exact cap, disclosure, review, source/requirement authority, task routes and schema-12 contract.

## Supplied material

[Managed intake](INTAKE.md) stores immutable uploaded content. Historical metadata-only records remain readable, but cannot supply content for learning; upload the original material. Teach message `disclose_attachments=true` explicitly authorizes selected originals in funded preparation. Setup `source_queue=true` selects a bounded standing source allowance. False/omitted fields preserve historical replay fingerprints. Retained material can be selected after reload; upload alone cannot teach or disclose it.

## Interaction readiness

Options and conversation detail expose application-authored prerequisite reasons for disabled remote access, unavailable connections/purposes/prices, expired/closed/exhausted allowances and suspended spending. The console retains unsent text in tab-local session storage, keyed by model/channel/conversation (when browser storage is available), and keeps saved results readable while disabling Send until the prerequisite is resolved. The API also checks before creating a turn or queued work; dispatch rechecks authority independently. Re-enabling a connection neither renews an allowance nor resubmits a message. Model-context mismatches remain separate revision checks. Teach budget bootstrap and retained-preparation renewal are explicit local actions.
