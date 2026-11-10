# Automatic teaching execution and follow-up

A durable parent task coordinates bounded acquisition, construction, source processing and admission. The engine remains domain agnostic. Recorded fixtures exercise orchestration without a live provider account.

## Owner workflow

Prepare and save a specification in Teach, then choose **Start teaching…**. The execution confirmation covers the exact specification, remaining allowance, disclosure and admission policy. Saving a specification alone grants no execution authority. Start creates no new cap and never borrows from Ask's interaction lane. If review time is insufficient, **Review more time…** offers a separate confirmation for the same retained preparation and remaining allowance. It starts no work.

The service visits dependent children in order, constructs private drafts, checks complete proposals, supplies bounded checked diagnostic feedback and admits eligible candidates. Independent owner requirements must already be installed for automatic admission. Without them, Teach shows a candidate's proposed behavior and asks for a semantic decision. Candidate definitions and receipt identity remain in Details. Approval still passes through ordinary local admission; it is not a proof of external truth.

Pause prevents new dispatch and publication. An already dispatched call may finish and remain charged. Resume uses the original scope and deadline. Cancel fences remaining publication and preserves accepted knowledge and provider accounting. A changed model, mode, owner policy, source policy, vocabulary or spending authority requires a fresh task decision rather than reusing an old approval.

A completion summary separates accepted capabilities and unresolved objectives, shows settled cost and retained reservations, and includes any fresh local answer. Provider prose is separately labeled explanation; it cannot replace the deterministic checked outcome. If narration fails or its allowance is unavailable, the outcome remains readable.

## Authority and persistence

The approved `awm-adm-teaching-specification/1` is immutable. An `awm-adm-teaching-execution/1` record adds its current context, owner/spending/learning generations, deadline, admission policy, stable child identities, review, follow-up and outcome. Task commands require the exact specification digest, current context, execution version and (for review) candidate digest. Replaying the same command returns the original acknowledgement. A changed command under the same identity conflicts.

Schema 13 adds `teaching_commands`; the execution record lives with its task. Registry reservations and ADM records have separate transactions. A stable, durable creation intent precedes child reservation/creation, and a lost acknowledgement reattaches the same episode. Existing provider grants preserve at-most-once dispatch and uncertain reservations. Provider text cannot set an internal episode's parent ownership.

Candidate publication updates the model revision, evidence support, receipt decision, child acceptance and parent's current context in one ADM transaction. The parent fence is checked before dispatch and after local computation, immediately before publication. The AWM-ADM review endpoint cannot bypass a teaching parent's semantic decision. Receiver receipt order and forward/backward precedence remain the existing engine contract; switching modes affects future decisions and invalidates old task authority.

## Lifecycle and bounds

A prepared task becomes queued, then running. Children progress through a persisted creation intent, bounded episode and accepted or unresolved outcome. Tasks may await a decision or pause. Terminal outcomes are succeeded, partially succeeded, failed, exhausted, cancelled or needs input. Continuation after terminal disposition uses a new task; neither remaining objective nor budget is silently expanded.

Each acquisition child allows at most two calls and two no-progress attempts, further constrained by the installation and parent allowances. Local episode work is at most six million units; each compute invocation is at most one million units and five seconds. Parent preparation and execution share the existing six-call, 192,000-input-token, 49,152-output-token, 16-child-record, 12-million-work budget and price expiry. One completion call and 4,096 output tokens remain protected. Dollar, token, local-work or time limits may stop before any capability is learned.

An unchanged, unstarted preparation can receive an explicit time-only renewal of at most one hour, bounded by its current pinned price. Up to eight renewals are retained. The exact owner/model/price/configuration and installation generations are rechecked; closed allowances, unsettled calls, changed preparations and execution already underway are ineligible. Original dollar/call/token/child/work caps and charges remain unchanged under the same allowance identity. Restoring an expired allowance must fit current installation financial and completion holds. A registry journal commits the old/new authority with accounting before an idempotent per-model handoff; recovery never repeats preparation or starts execution. The approved specification and previous proposals retain their original bytes. A new preparation review and Start decision remain separate.

Complete candidates can await a semantic decision for at most 24 hours. Their admission uses retained local-work capacity and grants no new outbound work after the active deadline. Start also reserves local vocabulary and, where applicable, exact-query follow-up capacity. Accepted source receipts are reconciled before deadline disposition. Final local work can complete within the retained review window (or the bounded one-minute completion grace); no late provider narration is authorized. The summary separately reports accepted/unresolved objectives, vocabulary installation and narration availability. Invalid proposals use the existing bounded diagnostic loop. Backward precedence rejection and unknown provider outcomes are terminal for that episode; neither triggers acquisition to evade the decision.

On restart, known queued intents, received outcomes and retained local candidates can continue under unchanged authority. Interrupted dispatched work is not repeated. Unfinished preparation and unacknowledged or uncertain outbound handoffs stop conservatively. Accepted work survives; completion delivery is durable and does not duplicate its conversation turn. Restore disables remote/spending authority as before, so restored tasks cannot silently resume paid work.

## Vocabulary, follow-up and current scope

After all capability children are accepted, the approved vocabulary is checked against the accepted model in a bounded local process and installed with its new generation and parent binding atomically. Incomplete tasks or interrupted vocabulary checks leave vocabulary uninstalled and record that limitation. Provider-proposed requirements and source permissions remain uninstalled; they never become independent acceptance authority automatically.

When the task links an existing pending Ask query, admission can authorize one new local request with the exact original query and a fresh current revision. The original request, attempt and presentation remain unchanged. The new result and its provenance are retained in the task and delivered to both Teach and the originating Ask conversation. A gap without an executable local query requires further Ask clarification; language does not invent a query or repeat interpretation without authorization. A local inconclusive or failed result is reported as such, including unavailable required Lean checking.

Capability and correction children use explicit finite interfaces. Supplied-material children use [managed intake](INTAKE.md), including uploads, extraction/projection, semantic review and ordered admission. Mixed ordinary tasks share one parent allowance. Dependencies on unresolved children remain unresolved; independent accepted work remains available. Standing intake uses one source-only task and an explicitly funded source allowance.

## API and implementation

Owner-only `POST /api/v1/adms/{adm}/tasks/{id}/commands` accepts `start`, `pause`, `resume`, `cancel`, `approve`, `decline` and source-intake `finish`, with an idempotency key, specification digest, context, expected execution version and optional review digest. Owner-only `GET`/`POST /api/v1/adms/{adm}/tasks/{id}/renewal` preview and confirm time-only renewal. `teaching.renewed` records the handoff, with full old/new scope in the local operation journal. Task detail and conversation Details expose the durable execution and child ledger. Events include `teaching.execution` and `teaching.completed`; existing candidate/request events retain their original meaning.

Implementation: [execution coordinator](../src/awm_adm/teaching/execution.py), [closed commands](../src/awm_adm/teaching/execution_models.py), [learning publication fences](../src/awm_adm/learning/service.py), [task UI](../console/src/TeachingTask.tsx). The Python scheduler, interpreter and transaction code remain trusted implementation; these checks are not a refinement proof.
