# Teaching preparation readiness

Preparation separates missing information from unsupported capabilities before learning begins. A missing date, unit, entity, representation bound, source passage, revision target or adoption decision is an information gap when supplying it would make a supported representation possible. The service asks one focused question. A capability is unsupported when the requested operation or representation remains outside the available contract even with the necessary information supplied.

The provider proposes this classification; it is not a proof of representability. The service validates the assessment structure and derives the workflow outcome. It never infers routing from explanatory wording or treats an arbitrary provider-selected status as authoritative.

## Provider contract

Fresh material-aware preparation uses prompt `adm-teaching-preparation/18` and [reply profile 6](../contracts/teaching-readiness-reply.schema.json). Preparation without a material manifest uses prompt `/19` and [reply profile 7](../contracts/teaching-legacy-readiness-reply.schema.json). Both use the same assessment fields and guidance, independently of the configured model.

Every field is required; inactive arrays are empty and inactive nullable fields are null. Unknown fields are rejected.

| Field | Meaning and local limit |
| --- | --- |
| `profile` | Exact reply profile selected by the dispatched task |
| `message` | Summary, 1–2,000 characters; not a routing instruction |
| `missing_information` | Up to eight gaps: `kind`, `input_ids`, `subject` (1–200 characters), `detail` (1–1,000) |
| `unsupported_capabilities` | Up to four limits: `kind`, `input_ids`, `requested_capability` (1–300 characters), `limitation` (1–1,000) |
| `question` | One natural-language question, 1–2,000 characters, or null |
| `plan` | The complete existing typed plan, or null |

Gap kinds are `meaning`, `entity`, `unit`, `representation_bounds`, `temporal_scope`, `source_material`, `revision_target`, `adoption_intent` and `other`. Capability-limit kinds are `unsupported_operation`, `unsupported_representation`, `unbounded_domain` and `resource_limit`. Each item references one to four unique, exact supplied input IDs. Blank item descriptions and foreign/duplicate IDs are rejected. The question asks for meaning or evidence, not internal schema repairs or source mappings.

| Checked assessment | Workflow |
| --- | --- |
| At least one gap; no limits; no plan; nonblank question | `needs_input`, displaying the question and retaining a resumable clarification |
| At least one limit; no gaps; no plan; null question | `unsupported`, displaying the limitation summary |
| No gaps or limits; complete plan; null question | Pass the plan to the existing preparation validators, then the normal learning lifecycle |
| Contradictory lists, missing reason/plan, unexpected question or invalid structure | `failed` / `invalid_preparation`, with bounded diagnostics; no learning or automatic retry |

If missing information prevents deciding whether the objective is representable, the provider should clarify it first. It must not invent bounds, silently drop parts of the request or coerce a different meaning to avoid a question. If the available context already supplies the answer, it should use that context.

## Persistence and continuation

The interaction, task and work retain an optional `preparation_assessment` with profile `awm-adm-preparation-assessment/1`, derived `kind` (`missing_information`, `unsupported_capability` or `ready`), the two lists, the question and `classification_authority: provider_proposed`. Older work has no such field. This diagnostic record grants no model, policy or provider authority.

A missing-information question uses the existing explicit `reply_to` continuation. The original inputs, selected immutable material and question remain linked within the existing four-input/24 KiB bounds. Clarification survives restart. Reading, polling or replaying the original idempotency key does not create another call. A new user reply authorizes a fresh preparation under the current context fences; no idle wait extends or changes a model's knowledge. The plugin presents the service's question and submits the user's answer through this same interface.

No extraction, acquisition, source-policy installation or publication starts from a non-ready assessment. A ready assessment alone is not accepted knowledge: the original plan grammar, finite carrier checks, exact material/span checks, source semantics, requirements, conflict precedence, dependency handling and admission remain authoritative. Invalid generated plan fields keep their existing plan/type/source diagnostics rather than becoming questions for users to fix.

## Compatibility and assurance

Previously dispatched prompt/reply profiles retain their original decoders. Old unsupported outcomes are not rewritten as clarifications, and failed or uncertain calls are not automatically repeated. The ready-plan grammar is shared with the corresponding non-assessed profile. Provider descriptions explain information gaps and local field bounds; historical dispatched instructions remain intact. See [teaching format and diagnostics](TEACHING.md) for concise objectives, exact original inputs and safe length/count failures. The assessment envelope does not change model formats or algebraic reasoning.

Structural checks cannot prove that the provider chose the right gap or capability category, that its question is semantically complete, or that supplied evidence is externally true. Recorded-provider regressions establish routing, persistence, continuation and unchanged validation. They do not establish live interpretation reliability across arbitrary requests.
