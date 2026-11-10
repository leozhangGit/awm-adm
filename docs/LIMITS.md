# Bounded defaults and price contract

The runtime enforces finite account, conversation, spending, task, queue and local-compute limits. Machine-readable hard ceilings are in [`defaults.json`](../contracts/workflows/defaults.json); the serialized profile identifier `awm-adm-v3-defaults/0.2` is retained for compatibility. [Spending](PRICED_ALLOWANCES.md), [teaching](TEACHING.md) and [execution](TEACHING_EXECUTION.md) describe narrower operational limits. Owner choices can lower limits; larger hard ceilings require a validated release change. Unknown pricing/usage never means free work.

## Defaults

| Area | Default | Hard bound / semantics |
| --- | --- | --- |
| Paid authority | Disabled; no implicit USD cap | Owner enables interaction and task/source allowances separately |
| Message | 16 KiB UTF-8 | 64 KiB; input envelope 2 MiB |
| Selected context | 6 turns / 16 KiB | 12 turns / 64 KiB; prioritize current user intent and bound references |
| Teaching task | 8 children, 6 provider calls, 2 no-progress attempts | 32 children, 20 calls, 3 no-progress attempts |
| Task active deadline | 15 minutes | 60 minutes; owner review may wait 24 hours, cannot dispatch after active deadline |
| One provider call | 32,000 input / 8,192 output tokens / 60 seconds | 1,050,000 / 16,384 / 120 seconds; all must fit parent/installation bounds |
| Per-step local work | 1,000,000 units / 5 seconds | 10,000,000 / 30 seconds |
| Aggregate task local work | 12,000,000 units | 100,000,000; repairs and preparation charged |
| Completion reserve | 1 call / 4,096 output tokens | Within parent call/token/money caps; no borrowing from interaction |
| Provider capacity | 2 installation slots: 1 reserved interaction, at most 1 background | Per-ADM total 2, background at most 1; the old single shared per-ADM slot cannot block the interactive lane |
| Local capacity | 2 serving processes, 1 conversation-check slot, 1 background slot | Existing process isolation plus separate fair queues; no unbounded child spawning |
| Source attachment | 256 KiB; 4 attachments/message | 1 MiB; 8 attachments, total request still ≤ 2 MiB |
| Source queue | 100 items / 8 MiB per ADM, 4 pending processing items | 1,000 items / 64 MiB, 16 pending; existing storage caps still apply |
| Source acceptance rate | 60 items/minute per credential and ADM | 600; bursts bounded by queue/call/storage caps, durable receipt before acknowledgment |
| Clarification | 4 questions per task | 12; batch related questions; stop with a useful unresolved summary |
| Stored task/turn capacity | 100 tasks per ADM / 200 turns per conversation | 1,000 / 1,000 within instance bytes; reject new work before silent eviction |
| Proposal decision | 10 minutes | 60 minutes, exact context/digest binding |
| Bootstrap / recovery redemption | 15 minutes / 10 minutes | Single use, local operator issuance; no permanent browser bypass |
| Browser session | 8 hours | Revocation on account/recovery events; loopback same-origin profile |
| Login attempts | 5 failures per 15 minutes per account/source | Bounded backoff and generic errors; local recovery remains available |

The runtime enforces all token/call/time/currency dimensions together. It must reconcile AWM-ADM episode defaults with these parent task limits rather than assuming a larger task automatically enlarges an existing episode. Each concrete child gets its own caps. The runtime keeps existing bounded episodes beneath their parent allowances; funding a larger parent does not enlarge child caps.

Reserve interaction capacity in shared call/token quotas as well as dollars and process slots. The initial 24-hour installation partition is interaction **40 calls / 1,280,000 input / 327,680 output tokens** and learning **60 / 1,920,000 / 491,520**. Per ADM it is interaction **8 / 256,000 / 65,536** and learning **12 / 384,000 / 98,304**. These sum to the existing default total envelopes. Explicit connection tests use an authorized control reservation deducted from the selected installation allowance without using protected interaction capacity. Learning cannot consume the interactive remainder of a shared quota. Unknown calls remain charged beyond the quota period. Lower limits may reject a task; no automatic enlargement follows from its dollar cap. Shared provider-account limits remain external constraints.

## Purpose and authority

Interaction pays for Ask interpretation/narration and bounded intent/budget clarification. Learning pays for task compilation, acquisition, source extraction, repair and its completion narration. A connection test has a separate explicit one-call control allowance; it cannot hide inside normal learning or interaction. Purpose-to-lane mapping is server-owned and included in the dispatch digest. A provider proposal cannot relabel a call.

Initial setup has a bootstrap problem: no paid LLM clarification can occur before permission for such a call exists. Secure provider setup therefore offers a deterministic short consent prompt with an exact initial interaction amount/expiry. Subsequent clarification can use the configured LLM. This does not require JSON or task-parameter forms, and local account creation spends nothing.

USD allowances are positive integer microdollars after authorization. No default paid amount is silently chosen. The schema allows at most 1,000,000,000 microdollars ($1,000) for an individual configured allowance; larger installations require a new bounded profile. Task and standing-source caps are lifetime amounts; interaction caps are fixed explicitly authorized windows (default 24 hours) with no automatic refill unless a separately specified standing policy is later implemented. Outstanding reservations stay charged after expiry and cannot be escaped by opening another window. Shared installation limits account for overlapping allowances.

## Price records and conservative reservation

A price record binds provider/model/configuration, USD input and output microdollars **per 1,000,000 tokens**, a validity interval, allowed billing categories and counting-bound evidence. It contains no real rate in the specification fixtures. Use integer ceiling arithmetic:

`reserved_micro_usd = ceil(input_bound * input_rate / 1_000_000) + ceil(output_cap * output_rate / 1_000_000)`

The input bound includes all serialized messages, schemas, system framing, tool declarations and applicable billable additions. Discounts can be ignored conservatively; reasoning tokens must be covered by a total billed output cap/rate. Additional tool/session/media charges are forbidden in this initial profile. Unsupported categories stop priced dispatch before egress.

Accepted bound methods for later transports are (a) documented provider preflight over the exact payload/configuration, with any preflight cost itself authorized; (b) a verified local count with a documented conservative allowance for every billed framing component; or (c) the documented maximum billable context for the selected configuration, charged at the highest applicable input rate. A byte estimate or a locally inferred tokenizer count without framing evidence is not sufficient. Reserve under all enclosing caps before creating an issuable grant.

The finite contract oracle uses a **synthetic recorded provider** with explicit bounds and rates. Supported live profiles are separately defined in [priced allowances](PRICED_ALLOWANCES.md), with pinned evidence, validity intervals and payload restrictions. An unsupported or expired price profile prevents priced dispatch; the synthetic arithmetic tests do not certify a live model or rate.

Usage settlement converts known token usage at the bound rate and releases only provably unused reservations. Unknown or zero-unverified remote usage retains its full reservation. Overrun is charged in full and suspends further affected dispatch; it cannot be silently clamped to the cap. The ledger is app-side accounting, not a verified provider invoice. Price invalidation pauses further dispatch; it does not change the valuation of a past call or silently refresh its authority.

## Synthetic arithmetic examples

At test-only rates of $2/million input and $4/million output, 32,000 input plus 8,192 output reserves **96,768 microdollars ($0.096768)**. Reported 1,000 input and 200 output settles **2,800 microdollars**, releasing 93,968. An unknown outcome retains all 96,768. A cap of 90,000 cannot authorize that call. Token-level rounding is tested at one-token boundaries; negative/Boolean/float amounts are rejected.

Historic AWM-ADM grants without a pinned price remain `unpriced_legacy`; their exact token/call reservations survive. New paid work is blocked until a conservative installation hold is configured, or the uncertainty is reconciled using actual evidence. The ledger never guesses old dollar costs, deletes reservations or enables paid dispatch. Read-only local serving remains available regardless of either paid lane.

The implemented application [conversation coordinator](CONVERSATIONS.md) uses these default bounds for messages, history, clarification depth and decision expiry. Teach clarification uses `clarification`. Ask separately authorizes `ask_interpretation` and optional `ask_narration` through exact local setup and owner confirmation. Existing clarification authority does not expand. Narration has a separate child/grant reservation; when remaining interaction capacity is insufficient, a deterministic local outcome is shown without a call. See [Ask](ASK.md).

## Implemented managed intake

The [source intake profile](INTAKE.md) implements the default attachment/backlog/rate bounds above, not the optional larger installation maxima. Its explicit source-only standing allowance lasts up to 24 hours (bounded by price expiry); ordinary tasks start with 15 minutes. An unchanged unstarted preparation can explicitly renew time within one hour, up to eight confirmations, without refilling any resource cap; see [teaching execution](TEACHING_EXECUTION.md). It retains six calls and 12 million local-work units without refill. Per-item extraction/projection/admission reserves three bounded local phases; policy installation and supersession holds reserve separately. Accepted facts survive later exhaustion. Short-lived append credentials expire no later than their task.
