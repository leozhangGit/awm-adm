# Teaching through conversation

See [knowledge intent](KNOWLEDGE_INTENT.md) for adopted rules, sourced observations, model-relative premises and exploratory or quoted material.

Open a model's Teach tab, describe a rule or supply a text/Markdown file, and send. An enabled [connection](CONNECTION.md) is the only remote setup. The service prepares the intended finite meaning, acquires candidate definitions or extracts supplied facts, checks them locally and publishes accepted work automatically. It asks a question when meaning or a necessary protected decision is unclear. There is no routine prepare/start/approve sequence or financial allowance.

Preparation makes the intended subject/property/value or event scope queryable, keeping observation and source clocks separate. A saved calculation is earlier attributed evidence; a reusable computation requires an executable capability. Successful admission does not certify every intended natural-language question. See [queryable knowledge](EVIDENCE_RECALL.md).

## What the model learns

Executable rules become typed definitions with explicit finite inputs and outputs. Observations become dated facts with exact source versions and byte spans. A mixed request uses separate children for rules and observations. The model-neutral preparation format preserves input references, type headers, units, dates and dependency order. Ambiguous bounds or correction targets require clarification. The provider cannot install a definition merely by describing it in prose.

Shared [meaning and representation guidance](TEMPORAL_INTERPRETATION.md) explains typed field encodings without supplying domain rules. Preparation captures the system timezone; explicit user/source zones take precedence. Provider source bounds must use canonical UTC instants, with the intended period preserved. The strict local source validators remain unchanged.

The service captures current revision, support, owner policy, source policy and vocabulary. A clear local Teach submission authorizes its checked execution. This authority is recorded as automatic teaching, not as individual human review. Existing independent requirements remain mandatory and cannot be weakened through a teaching proposal. A request to create new independent acceptance requirements needs a separate policy decision; the structured requirements API remains available.

## Preparation inputs and evidence

Preparation provider calls have a three-minute default deadline, within the exchange's existing active-work bound. A timeout ends preparation without starting learning and preserves unknown provider completion/usage. The chat and plugin retain a specific failure reason, timing and dispatch identity rather than treating every failure as a disabled or unavailable connection. See [provider deadlines and diagnostics](PROVIDER_FAILURES.md); local plan and admission validation remains unchanged.

[Preparation readiness](PREPARATION_READINESS.md) uses separate structured information gaps and capability limits. The service derives `needs_input`, `unsupported` or readiness from this assessment. Missing inputs produce a focused question; invalid generated structure fails preparation. No partial plan or assessment bypasses local validation.

Each new task retains a service-owned `awm-adm-teaching-materials/1` manifest before dispatch. The [provider reply contract](../contracts/teaching-readiness-reply.schema.json), `awm-adm-teaching-reply/6`, proposes one finite `plan.evidence_scope` catalog for all selected source material. It can combine exact instants, uncertain occurrences, validity intervals and whole-period values, preserving attributed reports separately from actual outcomes. Each source child selects its own `material_ids` from the manifest; it cannot invent source permissions or physical evidence identities. Capability-only plans use a null catalog. The service expands the shared catalog into the checked `awm-adm-teaching-plan/2` contract. Existing material, carrier, scope, source and admission checks remain authoritative. Retained preparation profiles use their recorded decoders, including the [shared-projection reply](../contracts/teaching-shared-reply.schema.json); they are never silently reinterpreted or retried. See [temporal evidence](TEMPORAL_EVIDENCE.md) for identity, limits and compatibility.

The shared mapping describes permitted entities, predicates and time cells, not observed facts. Unobserved combinations remain unknown. Compatible facts may share a mapping within the current source-policy and finite limits, including at most 4,096 entity–predicate–time combinations. Different units, incompatible carriers or temporal meanings must not be coerced to fit; unsupported meaning reports its concrete limit, and missing meaning can require clarification.

Fresh material-aware preparation uses prompt `adm-teaching-preparation/18` with reply profile 6; preparation without a material manifest uses prompt `/19` with reply profile 7. Retained work is decoded using its dispatched provenance: prompts 3–7 and 13 use reply 2, prompt 8 uses reply 3, prompt 9 uses reply 4, prompts 10–12 use reply 5, prompts 14/16 use reply 6, and prompts 15/17 use reply 7. Saved work is not rewritten or automatically retried.

The provider-facing schema stays shallow and closed. Its descriptions state the local string-length, collection-size and numeric bounds, derived from the same schema used for local validation. Descriptions supplement the existing semantic guidance without adding provider grammar constraints or changing acceptance rules. For example, each child objective is a concise summary of 1–2,000 characters; a plan has at most four children and 128 type nodes. Summary, message and question fields also have their own stated character bounds. These are output-format requirements, not instructions to narrow the user's domain or remove exceptions.

The original teaching inputs remain linked by exact `input_ids` and pass separately to acquisition with their detailed requirements, assumptions and evidence. A short objective does not replace that material. The provider must not copy a whole policy into the objective, truncate original text or split an atomic correction to fit a field. Local validation rejects oversized output rather than repairing it silently.

Length failures retain safe numeric `actual_length`, `max_length` or `min_length`, and `unit` (`characters` or `items`) beside each issue's code and sanitized path. Character counts follow the string validator, not UTF-8 byte length. Readable failures report the actual and allowed counts. Raw field values, arbitrary map keys and validator messages are excluded. An invalid generated field remains `failed` / `invalid_preparation`; it is not a question asking the user to repair an internal plan.

All intention turns remain linked through child `input_ids`. Evidence selection is separate: choose original messages and/or selected files containing observations or explicitly adopted model premises with their scope. Exclude replies that supply only instructions or representation bounds, while retaining them as linked context. Pasted originals in one explicit Teach lineage share a source collection and retain distinct items, exact UTF-8 digests and original conversation/turn origins. Selected uploads keep their original identities. Supplied materials share a conservative evidence group unless an existing independent source policy says otherwise; splitting a conversation does not establish independent corroboration. Cited URLs are attribution, not proof of fetching or external verification.

The same resolver checks selected identities, input links, permissions and original bytes before execution and ingestion. Unknown, duplicated, foreign, unselected or changed references fail before source-policy mutation or publication. Instructions are not automatically observations, and a selected file does not suppress selected pasted evidence.

An explicit reply to unfinished preparation retains its chosen task lineage even if the earlier clarification is already answered. It preserves up to four inputs and the existing 24 KiB encoded input limit. Separate branches do not acquire each other's replies. Accepted/executing/cancelled work is not replayed; accepted knowledge is consulted through the current model. Overflow requires a focused restatement, without silently dropping original facts.

Entity identifiers, nonempty units (including `unitless` when appropriate), bounds and temporal encodings follow shared model-neutral guidance. Local validators remain authoritative; missing meaning asks a question, whereas an invalid generated field or evidence reference produces `failed` / `invalid_preparation` with bounded stage/code/path diagnostics. Such a failure creates no clarification question and no automatic preparation retry. Failed checked specifications are retained for diagnosis but cannot execute.

## Learning and admission

Temporal catalogs receive field-level guidance for qualified predicate symbols, exact units, finite carriers and scope semantics. Exact instant coordinates use second precision and no end; uncertain occurrences retain bounded windows. Sanitized diagnostics preserve `evidence_scope` paths and add fixed identifier/time contract hints. No generated value is silently prefixed, coerced or repaired, and these annotations do not replace local validation.

The existing private construction engine performs propose/check/diagnose/revise. Complete candidates pass full admission; partial and rejected drafts never serve queries. Children have immutable acquisition contracts and dependency order. Each child allows at most two acquisition attempts, with finite work and call time/output bounds. Checked diagnostics can guide a revision; an unknown dispatched outcome is never automatically retried. The running task has a finite execution window, but idle clarification replies do not expire.

Backward mode rejects a later conflicting batch. Forward mode can replace conflicting content only through the same checked admission, including dependent definitions. Mode changes affect future admission decisions. Teaching does not change mode automatically. A task rebinds after its own atomic publication; unrelated model or policy changes stop stale work rather than silently authorizing a different proposal.

Conversational corrections preserve accepted dependent definitions in the same atomic candidate. Preparation follows the model's transitive dependency graph, adds the required dependent interfaces and pins their exact accepted bodies. Acquisition changes only the explicitly revised definitions; retained bodies are reconstructed locally and checked again with the new dependencies. This preserves syntax, not old computed answers or proof status. If a dependent assertion, type or owner requirement no longer holds, the candidate cannot publish. Overlapping corrections must form one child; the existing 32-declaration bound and unsupported-presentation boundary still apply. This behavior is independent of domain names and provider model choice.

Automatic checking does not prove that the LLM understood the owner's intention or that supplied facts are externally true. The completion reports accepted objectives and unresolved work separately. Independent intent fixtures, requirement checks, conflict tests and evidence tests verify these distinct boundaries.

## Supplied material and intake

Files are stored with their name, content hash and exact original bytes. Uploading alone performs no extraction, learning or publication. Sending selected files in Teach authorizes their use for this request. Only selected material and the request's bounded model/diagnostic context are disclosed; other files and conversations are excluded.

A prepared fact scope selects finite entities, predicates, units and time cells. The service installs an initial source mapping when justified by the teaching request, or reuses an existing mapping. A later request can reuse a subset or add finite coverage through the existing checked coverage-extension operation. Every retained time cell, predicate carrier and unit is preserved; overlapping reinterpretation or a changed value range requires clarification. Existing facts remain supported, and uncovered dates remain unknown.

Managed source work uses the existing durable feed queue with throttling, per-item computation and dispatch identities. Clear extracted claims proceed through local validation and admission with `automatic_teach` provenance; they are not labeled individually owner-reviewed. Corrections retain source versions and supersession history. Missing, disputed, rejected or unsupported evidence remains unresolved. Source/feed APIs also remain available for explicit ingestion and bounded connector workflows.

## Clarified source material

For a one-shot source task continued through clarification, the service processes selected originals and linked textual replies together. It creates an immutable selected-material packet with original source/item/version references, content hashes and UTF-8 payload offsets. Unselected uploads and unrelated history are excluded. The packet is ordinary source text under the existing extraction, span, temporal, projection and admission checks; its metadata and instructions do not assert facts. No partial packet is dispatched if existing input or byte bounds are exceeded.

Original messages/uploads remain intact. Accepted evidence and snapshots retain the complete packet, so its interpretation does not depend on later chat-history retention. Correcting an included original source holds affected packet-supported facts through the existing source-dispute mechanism. A fresh extraction or projection cannot reuse the packet to bypass a known original-source correction. Historical executions keep their original material/dispatch identities. Standing queues retain per-item processing.

## Completion, failure and recovery

The saved completion summary identifies accepted and unresolved objectives. A provider explanation may elaborate on that exact outcome packet; it cannot replace the model result or claim an unperformed action. If narration fails, a readable local summary remains. Ask continues independently while learning runs. Pending requests and earlier accepted knowledge are retained if a task fails or exhausts computation.

Actual publication effects accompany completion. When an older/in-flight task publishes only part of an objective and removes a dependent capability, the summary identifies the saved declarations and the unresolved preservation requirement instead of claiming the entire objective was learned. A failure after publication retains accepted knowledge and separately reports unfinished language setup or local follow-up. New requests can still prepare against the accepted revision using compatible language metadata.

Cancellation fences publication. Restart recovery reconciles known local work without repeating an uncertain acquisition or dispatching a new explanation merely to reconstruct the display. Historical setup/financial intents are not replayed under automatic teaching. A task interrupted before execution asks for a fresh submission; its original material and preparation remain recorded.

## API

All routes begin with `/api/v1` and use the shared local service boundary.

- `POST /adms/{adm}/teach`: text, optional selected `attachments`, `reply_to` and `idempotency_key`.
- `POST /adms/{adm}/attachments`: store an immutable selected file; `GET` lists retained files.
- `GET /adms/{adm}/interactions/{id}`: readable status, summary and retained task references.
- `GET /adms/{adm}/chat/teach`: ordered history, with the same forward/backward cursor contract as Ask. The console initially displays the latest 100 exchanges; **Load more** adds up to 100 older exchanges without changing learning or conversational context.
- `GET /adms/{adm}/tasks/{id}`: exact preparation, execution and provenance for programmatic use.
- `POST /adms/{adm}/tasks/{id}/commands`: retained pause/resume/cancel controls with exact context/version fencing.

The preparation profile supports functions, types, assertions, goals and transitions in the implemented finite language. It does not synthesize arbitrary theorem declarations, refined carriers or algebraic presentations; the richer existing structured API/library capabilities remain available. Removing advanced console panels does not narrow the engine language.
