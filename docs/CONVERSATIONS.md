# Durable Ask and Teach

Each ADM has two visible streams: Ask for read-only questions and Teach for learning. The user types and sends a message without creating a conversation or setting up interaction authority. The single connection must be enabled for new remote work.

## Exchanges and context

The service creates an internal conversation and durable work record for each submission. It captures current model, policy, vocabulary and source-support context, plus the exact connection configuration. These identities stay in records and APIs; users do not manage them.

`POST /api/v1/adms/{adm}/ask` and `/teach` accept `text`, selected `attachments`, optional `reply_to` and optional `idempotency_key`. Ask refuses attachments; use Teach for supplied material. The server generates a submission identity when omitted. Clients should retain an explicit identity when they need reliable recovery after a lost response. An unchanged replay returns the original exchange; changed content under the same identity conflicts.

A follow-up names its originating interaction. The service retains at most six relevant owner turns within a 16 KiB context envelope, the pending semantic question and explicit saved-result references. It does not append the whole model history, unrelated API work or assistant prose as accepted premises. Another browser tab cannot change which exchange a reply refers to. A clarification reply captures the current accepted model again; waiting for that reply does not expire a financial allowance.

Ask and Teach are distinct. A new Ask submission cannot publish knowledge. A clear local Teach submission authorizes work within its meaning and selected materials; provider text cannot change a protected setting, switch modes or grant itself more scope.

## Durable reads

`GET /adms/{adm}/chat/{ask|teach}` returns retained channel history. The default forward direction uses exclusive `after` and preserves ascending pagination. `direction=backward&limit=100` selects the latest 100 exchanges; `direction=backward&before=N&limit=100` selects up to 100 older than the exclusive sequence N. Both directions return items in chronological sequence order with each item's `sequence`, `next_cursor` and `has_more`; in backward mode the next cursor is the oldest returned sequence. Do not mix `after` with backward mode or `before` with forward mode. New arrivals do not shift older page boundaries.

The console initially loads only the latest 100, then expands by up to 100 through **Load more** at the top. Polling refreshes the selected window and appends new arrivals without traversing unrequested older pages. Display selection does not change storage, the History search or the bounded follow-up context. A previous reply reference outside the displayed window is read individually when needed, without displaying its surrounding history or making a provider call.

`GET /adms/{adm}/interactions/{id}` returns a readable reply, progress, saved outcome and original result references. `POST /adms/{adm}/interactions/{id}/cancel` stops that exchange; repeating cancellation is safe. Already accepted knowledge and completed answers remain available.

Existing `/conversations`, conversation detail, `/details`, `/presentations` and `/tasks` reads preserve historical records. Retired setup, budget decision, conversation-creation and renewal routes cannot authorize work. Historical records remain evidence of what actually happened; they are not rewritten to look like automatic teaching.

[History](HISTORY.md) groups logical Ask/Teach interactions and explicit model/learning/source API activity. Reading it never repeats work or sends old content to a provider.

## Recovery and presentation

Browser polling and focus checks preserve the mounted composer, draft, selected files and scroll position. A retained send can be recovered with its original identity. No polling path creates work.

Application restart interrupts unfinished interpretation/preparation rather than replaying a dispatched call. Known local request identities can be reattached without repeating execution. A saved local outcome remains readable if explanation is unavailable. Teaching preserves accepted children and reconciles known work under its publication fences; uncertain calls remain uncertain.

Readable output distinguishes true, false, unknown, unsupported and inconclusive. Explanations are fallible prose bound to a result packet. Exact queries, attempts, revisions, evidence and provider accounting stay accessible through the API; no raw JSON or Details panel is required for normal use.
