# Task and operation lifecycle

This normative finite specification is exercised by [`lifecycle.json`](../contracts/workflows/lifecycle.json) and authored traces. It is not a runtime refinement proof. The implemented service uses durable SQLite records and the authority checks in [chat contracts](CHAT_CONTRACTS.md) and [teaching execution](TEACHING_EXECUTION.md).

## Teaching task

| From | Event → next | Required meaning |
| --- | --- | --- |
| draft | ask → needs_input; authorize → ready; cancel → cancelled | Preparation cannot acquire knowledge until scope and allowance exist |
| needs_input | clarify → draft; cancel → cancelled | A new checked interpretation incorporates the owner's answer |
| ready | enqueue → queued; cancel → cancelled | Durable task and child reservations precede dispatch |
| queued | start → running; pause → paused; cancel → cancelled; deadline → exhausted | Queued never means a worker is executing |
| running | ask → needs_input; review → awaiting_decision; pause → paused; unknown → paused; cancel → cancelled; fail → failed; exhaust → exhausted; complete → succeeded; partial → partially_succeeded | Completion records accepted children separately from failed/unresolved children |
| awaiting_decision | accept → queued; decline → failed; cancel → cancelled; invalidate → needs_input | Exact proposal/context checks apply; acceptance does not bypass admission |
| paused | resume → queued; clarify → needs_input; cancel → cancelled; exhaust → exhausted | Resume needs current authority and no unknown dispatched child; an explicit new attempt has a new identity and reservation |
| succeeded / partially_succeeded / exhausted / cancelled / failed | none | Terminal records are immutable; continuation is a new task linked to prior evidence |

Semantic guards accompany the shape/state table. `authorize` needs a current owner decision, valid independent policy/required review mode, priced allowance and bounded immutable contract. `complete` requires all intended children done and no unresolved outcome. `partial` requires at least one accepted result and at least one unresolved objective. If nothing was accepted, exhaustion/failure cannot be called partial success. `cancel` fences future publication and never rolls back already accepted knowledge or refunds spent/unknown calls.

A held complete candidate may await owner review beyond the active task deadline, up to the bounded review expiry. Accepting it then queues only a fresh bounded local admission check with remaining reserved work; it cannot dispatch another provider call. An expired incomplete task needs a new authorized continuation. If an unknown call remains unresolved, an explicit owner decision can create a new separately reserved task/attempt linked to the old task; it cannot relabel the old call undispatched or clear its reservation to make `resume` pass.

## Step and dispatch

| From | Event → next | Guard/effect |
| --- | --- | --- |
| prepared | reserve → reserved; cancel → cancelled | Atomic ledger reservation precedes child/grant publication |
| reserved | dispatch → dispatched; release_unissued → cancelled | Dispatch ledger writes once before egress; release requires proof no outbound request was issued |
| dispatched | response → known; lose → unknown | Timeout/lease expiry/lost response are unknown, not safe retry |
| known | check → checked; reject → rejected | Complete output only; no salvage of partial provider output |
| checked | admit → published; reject → rejected | Current authority/context, complete candidate, owner checks and ordinary receipt order |
| unknown | settle → known | Late identified outcome can settle usage; this is never a second outbound dispatch |
| published / rejected / cancelled | none | New repair requires a fresh child identity within an existing authorized policy |

A late outcome cannot publish after parent cancellation, expired authority or model deletion even if it moves an unknown step to known for accounting. Do not revive an expired AWM-ADM episode. The parent may create a new bounded child only when an explicit authorized repair/continuation policy and remaining budget allow it. Changing models, contracts, requirements or budgets is not a diagnostic repair.

## Recovery and context changes

| Situation | Permitted recovery |
| --- | --- |
| Browser closes or acknowledgment is lost | Retrieve existing task/message/operation by identity; never infer a new attempt |
| Safe local prepared step interrupted | Reconcile stored operation, then queue a fresh bounded local attempt if still authorized |
| Reserved outbound step has proven no dispatch | Release/recreate only through durable app/gateway reconciliation; absent record is insufficient if a dispatch intent existed |
| Dispatched provider step interrupted | Mark unknown, retain reservation, pause affected task; no blind retry |
| New model revision | Locally revalidate typed meaning; reset private construction as required; changed meaning/contract asks the owner |
| Owner requirements/mode/source scope changed | Fence old approvals; obtain current authorization before continuing affected work |
| Backward conflict rejection | Terminal precedence decision, not an invitation to retry until it wins |
| Current source evidence superseded | Hold dependent answers until fresh admitted support; preserve historical result bindings |
| Several independently valid candidates | Check each against current accepted state in receiver receipt order; individual consistency is not joint consistency |

Task progress is an aggregate of its durable children, not an LLM-authored status. Parent scope contains every child ADM, purpose and spending lane. A child's completion event and its durable outcome are committed together within the owning store; registry/per-ADM/gateway coordination uses reconciliation intents rather than a fictitious distributed transaction.

## Deletion

`requested → fenced → draining → purging → deleted`; failure at a nonterminal phase enters `blocked`, retaining `resume_stage`, inventory and operation identity. A retry resumes that exact stage. A failed cleanup never turns a deleting model back into an active instance.

Fencing precedes cleanup: reject new work, advance/revoke model-scoped authority, cancel private work and stop late publication. Draining reconciles shared interests and dispatches. Unknown external usage is detached into minimal installation accounting with its original dispatch identity and full reservation; it does not require retaining model content indefinitely. Purging follows an explicit inventory of model databases, source/conversation content, cached result packets and global payload references. Keep a content-free replay tombstone and accounting references only. Independent clones and shared provider connections remain intact. Backups/exported copies are outside active-instance deletion.

Tests inject interruption before/after every phase, owner decision races, attempted publication after cancel/delete, and attempts to resume an unknown call. The contract suite supplies finite traces; runtime tests exercise SQLite, the supervisor, gateway and paired restore. These checks are not a refinement proof of the full implementation. [Model lifecycle](MODEL_LIFECYCLE.md) defines the concrete transaction boundaries and retained inventory.

## Implemented language mapping

[Teaching execution](TEACHING_EXECUTION.md) binds learning prepared specifications to exact Start commands. Stable child creation intents reconcile registry and ADM handoffs; accepted publication and the parent context advance atomically. Unknown dispatches stop without repetition. External context changes conservatively terminate as needs input for a new task decision. Source-bearing children use the [source intake workflow](INTAKE.md), including exact disclosure, source consent and parent-controlled admission. The completion record preserves deterministic accepted/unresolved outcomes even when optional explanation fails.
