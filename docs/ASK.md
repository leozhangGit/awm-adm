# Ask: interpretation, local execution and explanation

Ask combines a checked read-only interpretation, local model execution and optional provider explanation. [Conversation contracts](CONVERSATIONS.md) govern exact input, funding and disclosure; [Teach](TEACHING.md) separately prepares new knowledge. The current owned storage schema is 15.

## User journey

Choose a model and open an Ask conversation. **Set up interaction** selects an enabled, currently priced connection. **Use for Ask and explanations** separately authorizes result disclosure; **Use for Ask only** leaves results local. Enter an exact USD cap and confirm the named scope. This setup makes no provider call and does not inherit AWM-ADM or clarification-only consent.

An ordinary question queues one interpretation. When its checked meaning is complete, the service submits a read-only local request automatically. There is no preview/confirmation click for that request. The conversation displays the actual local answer, verdict or plan in readable form. An optional **AI explanation · not a checked result** is presented separately. **Outcome details** exposes the saved request, context, outcome, packet and explanation validation; conversation **Details** also exposes provider accounting. Raw envelopes stay out of the main conversation.

A missing capability offers **Continue in Teach**. This owner action creates a separate, unfunded Teach conversation retaining the original Ask context and interpretation. It creates no learning episode, acquisition grant or publication. A stale original context requires a fresh question; an inconclusive computation is not a learning gap.

## Interpretation contract and limits

`conversations/ask.py` uses the existing model-neutral language catalog, controlled commands and bounded language compute child. The accepted vocabulary belongs to the ADM instance; shared instructions contain no fixture rules. Catalog entries omit declaration bodies, sources and credentials. Disclosed context consists of the current question, up to six owner turns from this conversation at the same model context (16 KiB encoded), the exact pending question/intent and explicitly linked successful-result identifiers (at most 32). Other conversations and assistant history are excluded.

The provider proposes `ready`, `needs_clarification`, `needs_learning` or `unsupported`, a controlled command or null, assumptions, and a clarification. Supported operations are capabilities, finite evaluation, Boolean claim checks, planning and an explicitly linked saved-result explanation. They preserve explicit entity/time/unit arguments, initial state, action selection and depth. Historical fact lookup is also supported under the conversation contract below. Certificate inputs remain in Local debug. Ask never changes mode, requirements, source policies, provider configuration or models, and never starts learning implicitly.

Ordinary ready commands are parsed and checked against the accepted catalog in a bounded network-free process, then rechecked before enqueue. Historical commands use the bounded strict decoder and typed FactLookup validation before the same context-fenced enqueue. Nonempty assumptions require clarification. Missing, invalid or ambiguous slots cannot yield a partial executable query. Reply identity binds the exact question and original intention. Context checks include revision, theory/support roots, owner epoch, vocabulary and source-policy generation; changes fence dispatch/enqueue and require fresh input.

**Type checking is not proof of understanding.** A provider could select a different well-typed entity or date. The independent [intent corpus](../contracts/ask-corpus.json) compares authored expected meanings separately from shape acceptance, local execution and presentation fidelity. Its deliberately wrong but well-typed entity example records this boundary. Recorded examples do not measure a live model's translation accuracy. Users can inspect the bound meaning and correct it with a new question.

## Durable execution and recovery

One exchange owns an immutable interpretation grant, and at most one deterministic local request identity (`ask:<work-id>`). The request and work link commit in the same ADM transaction with `on_gap=report`. Provider interpretation cannot specify a learning policy or execution side effect. Reconnect, duplicate submission and polling recover that identity; they never rerun a request. AWM-ADM explicit-preview routes retain their existing consent behavior.

| Phase | Durable behavior |
| --- | --- |
| queued / awaiting_provider | Exact priced interpretation child/grant; no local request yet |
| needs_input / needs_learning / unsupported | Checked unready intent; no local request or learning |
| awaiting_local | One existing request, separately scheduled by local serving |
| awaiting_narration | Local outcome saved; one separately reserved explanation grant |
| completed | Immutable presentation and completion turn/event commit together |
| failed / interrupted before enqueue | No automatically repeated call or query |

Conversation polling returns bounded work summaries; catalog, interpretation and disclosure packet bodies are loaded only through Details. The conversation worker does not hold the global store lock during bounded language computation. Interpretation checks and local serving use their existing separate compute capacity. Model scheduling rotates between ADMs. Queued work is distinguished from an actual provider lease/dispatch.

On application restart, unfinished interpretation stops. An already-created local request is reattached by identity; the local scheduler may have completed or interrupted it. Ask does not retry it. A recovered local outcome uses deterministic presentation without dispatching narration. Uncertain outbound reservations remain retained. A late or failed narration cannot hide a saved outcome; any failure after local completion produces the readable fallback. Saved outcomes remain bound to their original revision even if the model later changes.

## Result disclosure and grounding

Narration requires the explicit `narrate_results` preference and the `ask_narration` connection purpose. It uses the interaction lane, distinct from `ask_interpretation`. The packet is limited to 32 KiB and includes the exact request/attempt/result identity, query/scope, result binding, selected outcome fields, allowed claims, proof-status distinctions, empirical-fidelity status and reference identifiers. Source excerpts, arbitrary result-history text, credentials and hidden reasoning are excluded. A result identifier references its local provenance; it is not a disclosure of source contents. Oversized packets use the local renderer without disclosure.

A strict bounded reply must match the packet and outcome digests, exact outcome status and allowlisted claim/reference identifiers. Unknown references, added fields, forged outcomes and stronger unsupported claims reject the explanation. The application renders the authoritative outcome independently. Free prose remains unverified and explicitly labeled; matching structural claims does not make every sentence true. Safe text rendering cannot execute HTML, links or images.

Witness, shortest action count, unreachability and absence of a plan within a bound are separate claims. Inconclusive, missing input, failure and interruption never become a successful answer. A plan describes a computed sequence, not a physical action. Larger structured values and plans show bounded readable summaries with full data in Details. The engine's exact saved `Result` and finite-table hashes are unchanged.

## Accounting

The exact setup cap funds at most six provider calls, 192,000 aggregate reserved input tokens and 49,152 output tokens over at most one hour. Each call has 4,096 output tokens and a 60-second bound; an exchange has five minutes. One ready question normally needs one interpretation and optionally one narration. Clarifications consume additional calls within the same limits. The installed price profile supplies the billable input bound; no arbitrary model price is invented.

Each phase reserves its own immutable operation/wire identity before handoff. Narration is optional and has no guaranteed completion hold in an interaction allowance: exhausted funds/calls/children, revoked authority, unavailable provider, malformed reply or timeout yield the deterministic local outcome without another call. Unknown reservations are not refunds. Learning exhaustion cannot consume the interaction lane; provider outage cannot disable direct local serving.

## API and storage

New owner-only routes supplement the application conversation API:

- `GET /api/v1/adms/{adm}/interaction-options?purpose=ask` lists usable interpretation choices and narration availability.
- `POST .../conversations/{id}/setup` accepts `purpose=ask` and explicit `narrate_results`; both enter the exact confirmed proposal.
- `GET .../presentations/{id}` returns the immutable presentation with local outcome, packet, request reference and narration status.
- `POST .../ask/{work}/teach` takes current context and an idempotency key, preserving the gap in a separate Teach conversation.

Schema 11 adds `chat_presentations` and its conversation index, and advances the installation upgrade journal. Schema-10 conversations retain their original clarification scope. The presentation core uses `awm-adm-v3-presentation/0.2`, whose explicit `request` subject covers failed/inconclusive requests without inventing a successful Result; the specification `/0.1` result/task specification remains preserved. Its runtime schema is [ask-presentation.schema.json](../contracts/ask-presentation.schema.json); the endpoint wraps it with local outcome/debug fields. Existing AWM-ADM snapshots, results, histories and consent are unchanged. Paired restore disables financial/remote authority and preserves uncertain accounting.

## Historical fact questions

A newly reviewed Ask allowance explicitly discloses historical metadata from owner source configuration and accepted snapshots: finite entities, predicates, types, units and time coverage. The snapshot metadata is checked in a bounded local child, limited to 32 distinct profiles and 32 KiB, and excludes fact values and source bodies. Imported copies need no new source policy merely to ask about retained evidence. Existing preferences and pending older approvals are unchanged (including projection-only disclosure); renew setup to authorize this additional disclosure. Source bodies, provenance excerpts and other conversations are excluded. Coverage is not evidence that a fact is known.

The model-neutral `adm-ask-interpretation/2` prompt can propose `lookup fact with` followed by exactly `entity_id`, `predicate` and an explicit UTC `effective_at`. The closed decoder rejects duplicate/extra keys and invalid dates; unknown entity/predicate choices request clarification. The user's date is preserved even outside coverage. Missing or assumed dates require clarification; well-typed semantic mistakes remain possible.

Execution uses the existing durable local `lookup_fact` request and unchanged source-support checks. Unsupported dates and disputed evidence remain `needs_input`, never a fabricated value. A successful chat answer labels its entity, predicate and historical date and remains bound to the saved revision/support root. Outcome details retains exact bindings; source records and original provenance remain in Model & evidence and Local debug. No provider result becomes an admitted fact. See [integrated assurance](TESTING.md).

## Local historical controls

`GET /api/v1/adms/{adm}/history-options` supplies bounded entity, predicate, unit and coverage metadata from checked accepted snapshots and any current source projection, pinned to the current model context. Local debug uses it for historical lookup choices. Imported models need no new source-intake permission to query accepted history. This metadata carries no fact values or support verdict; only a fresh local lookup establishes an answer.
