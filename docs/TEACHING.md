# Teaching through conversation

Open a model's Teach tab, describe a rule or supply a text/Markdown file, and send. An enabled [connection](CONNECTION.md) is the only remote setup. The service prepares the intended finite meaning, acquires candidate definitions or extracts supplied facts, checks them locally and publishes accepted work automatically. It asks a question when meaning or a necessary protected decision is unclear. There is no routine prepare/start/approve sequence or financial allowance.

## What the model learns

Executable rules become typed definitions with explicit finite inputs and outputs. Observations become dated facts with exact source versions and byte spans. A mixed request uses separate children for rules and observations. The model-neutral preparation format preserves input references, type headers, units, dates and dependency order. Ambiguous bounds or correction targets require clarification. The provider cannot install a definition merely by describing it in prose.

Shared [meaning and representation guidance](TEMPORAL_INTERPRETATION.md) explains typed field encodings without supplying domain rules. Preparation captures the system timezone; explicit user/source zones take precedence. Provider source bounds must use canonical UTC instants, with the intended period preserved. The strict local source validators remain unchanged.

The service captures current revision, support, owner policy, source policy and vocabulary. A clear local Teach submission authorizes its checked execution. This authority is recorded as automatic teaching, not as individual human review. Existing independent requirements remain mandatory and cannot be weakened through a teaching proposal. A request to create new independent acceptance requirements needs a separate policy decision; the structured requirements API remains available.

## Learning and admission

The existing private construction engine performs propose/check/diagnose/revise. Complete candidates pass full admission; partial and rejected drafts never serve queries. Children have immutable acquisition contracts and dependency order. Each child allows at most two acquisition attempts, with finite work and call time/output bounds. Checked diagnostics can guide a revision; an unknown dispatched outcome is never automatically retried. The running task has a finite execution window, but idle clarification replies do not expire.

Backward mode rejects a later conflicting batch. Forward mode can replace conflicting content only through the same checked admission, including dependent definitions. Mode changes affect future admission decisions. Teaching does not change mode automatically. A task rebinds after its own atomic publication; unrelated model or policy changes stop stale work rather than silently authorizing a different proposal.

Conversational corrections preserve accepted dependent definitions in the same atomic candidate. Preparation follows the model's transitive dependency graph, adds the required dependent interfaces and pins their exact accepted bodies. Acquisition changes only the explicitly revised definitions; retained bodies are reconstructed locally and checked again with the new dependencies. This preserves syntax, not old computed answers or proof status. If a dependent assertion, type or owner requirement no longer holds, the candidate cannot publish. Overlapping corrections must form one child; the existing 32-declaration bound and unsupported-presentation boundary still apply. This behavior is independent of domain names and provider model choice.

Automatic checking does not prove that the LLM understood the owner's intention or that supplied facts are externally true. The completion reports accepted objectives and unresolved work separately. Independent intent fixtures, requirement checks, conflict tests and evidence tests verify these distinct boundaries.

## Supplied material and intake

Files are stored with their name, content hash and exact original bytes. Uploading alone performs no extraction, learning or publication. Sending selected files in Teach authorizes their use for this request. Only selected material and the request's bounded model/diagnostic context are disclosed; other files and conversations are excluded.

A prepared fact scope selects finite entities, predicates, units and time cells. The service installs an initial source mapping when justified by the teaching request, or reuses an existing mapping. A later request can reuse a subset or add finite coverage through the existing checked coverage-extension operation. Every retained time cell, predicate carrier and unit is preserved; overlapping reinterpretation or a changed value range requires clarification. Existing facts remain supported, and uncovered dates remain unknown.

Managed source work uses the existing durable feed queue with throttling, per-item computation and dispatch identities. Clear extracted claims proceed through local validation and admission with `automatic_teach` provenance; they are not labeled individually owner-reviewed. Corrections retain source versions and supersession history. Missing, disputed, rejected or unsupported evidence remains unresolved. Source/feed APIs also remain available for explicit ingestion and bounded connector workflows.

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
