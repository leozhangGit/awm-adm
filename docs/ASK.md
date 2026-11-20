# Ask: interpretation, ADM execution and explanation

Open a model's Ask tab and type a question. One enabled [connection](CONNECTION.md) makes remote interpretation and explanation available. No conversation setup, spending allowance or purpose selection is required. Ask is read-only: it never changes accepted knowledge, starts learning or changes the model's conflict mode.

## One visible history, independent exchanges

Each submitted message has a durable identity and captures the current accepted model context. The console displays a continuous history and manages follow-up references automatically. An API caller can provide `reply_to` when referring to a particular earlier exchange. Independent submissions do not inherit each other's conversational context or block behind an idle clarification.

The interpreter receives the question, up to six explicitly linked owner messages (16 KiB), the pending clarification and any linked successful-result identifiers. Other API callers' conversations and assistant prose are not automatically included. Clear follow-ups resolve references from these owner messages and retain unchanged inputs in the same scenario; the latest explicit value takes precedence. A resolved conversational reference is not an unresolved assumption. New subjects do not automatically inherit old inputs. Scenario inputs are not accepted facts or independently observed current conditions; the current model supplies the executable rules. A clarification has no financial expiry. A reply captures current model context, and a changed model is checked again before execution.

## Meaning and supported operations

The provider proposes an interpretation using the model-neutral catalog and accepted vocabulary. Supported operations are capabilities, finite evaluation, Boolean claim checks, planning, historical fact lookup and explanation of a linked saved result. Action selection, dates, units and initial states are checked explicitly. Missing, conflicting or genuinely ambiguous inputs require a specific clarification question. The provider's `assumptions` field is reserved for unresolved premises; any nonempty list still prevents execution. The service never silently discards reported uncertainty. Unsupported meaning produces no executable query. Certificate operations and richer algebraic constructions remain available through structured APIs/library contracts described in [the engine](ENGINE.md).

Temporal interpretation uses an explicit relevant user timezone or the service system default. A date-only historical question retains the entire civil day: application code resolves its UTC bounds and local execution checks the whole period. Missing coverage remains unknown; an answer that changes within the period calls for a narrower time. See [meaning and temporal context](TEMPORAL_INTERPRETATION.md) for precision, DST and disclosure rules.

Type checking cannot establish that the interpretation matches a person's intention. The independent [intent corpus](../contracts/ask-corpus.json) distinguishes semantic expectations from structural validity, including a deliberately incorrect but well-typed entity. The [interaction corpus](../contracts/interaction-corpus.json) covers ordinary messages and follow-ups. Recorded fixtures verify orchestration, not a live provider's general accuracy.

## Execution and explanation

A valid interpretation queues one local request with `on_gap=report`. The ADM executes it against accepted definitions and evidence. Provider prose cannot supply missing facts, turn an unknown result into false or bypass the checked model. Planning retains witness, shortestness, exhausted-depth and unreachability distinctions. Historical lookup preserves explicit dates and provenance; absent or disputed support remains unknown.

The explanation answers in ordinary language using a bounded packet of the computed outcome and the same selected owner wording used for interpretation. Owner wording helps express the answer; it is not additional evidence for the result. Routine assurance fields are retained in records rather than recited as chat warnings. A short, independently generated **Model answer: Yes/No/value** label keeps simple computed values visible beside the AI explanation. Historical values use the same compact label with a **Historical evidence** qualifier. Missing or disputed support and values that change within a requested period retain specific readable summaries. Complex and inconclusive outcomes retain their relevant limits. No label certifies the AI's prose.

Exact packet/outcome digests and allowed claims/references are validated. This checks structural bindings, not the truth of every sentence. Source excerpts, credentials and unrelated conversations are excluded. The packet remains bounded at 32 KiB including owner wording; if it is too large or narration fails, the readable ADM outcome remains available. Existing saved explanations are not rewritten or regenerated when guidance changes.

## Durability and limits

Each exchange owns one interpretation identity and at most one local request identity. Retries with an unchanged idempotency key recover that work; changed content under the same identity is rejected. Polling creates no work. A failed or uncertain provider call is never automatically repeated. On restart, an already-created local request is reattached and any saved outcome is retained; narration is not re-dispatched merely to rebuild the display.

Per-call time/output limits, finite local computation, queue capacity and bounded context protect the service. They are execution protections rather than financial setup. Ask has scheduling capacity independent of acquisition. Disabling the remote connection stops new provider dispatch, while supported structured ADM queries can still execute without a provider.

## API

All paths below begin with `/api/v1` and use the existing login-free local workspace access.

- `POST /adms/{adm}/ask`: `{ "text": "…" }`, optionally `idempotency_key` and `reply_to`. Returns a durable interaction immediately.
- `GET /adms/{adm}/interactions/{id}`: current status, readable reply, full local outcome, optional compact `outcome_label`, and request/result identities. The label is generated from the local result, not from provider prose.
- `GET /adms/{adm}/chat/ask?after=0&limit=20`: forward interaction pages, with `next_cursor` and `has_more`. Use `direction=backward&limit=100` for the latest page and `before=<next_cursor>` with backward direction for older pages; items remain chronological. The console opens with the latest 100 and loads older batches only on **Load more**.
- `GET /adms/{adm}/presentations/{id}`: retained exact presentation and result bindings for programmatic inspection.
- `GET /adms/{adm}/history-options`: bounded accepted entity/predicate/time metadata, without fact values or a support verdict.

The console uses these same routes. Internal conversations preserve each exchange's identity; users do not create or select them. Stored model, result and snapshot formats remain unchanged. Historical conversation records remain available for activity/history queries.
