# Conversational teaching preparation

Teach converts an owner's goal and conversational answers into a checked, reviewable specification. [Execution](TEACHING_EXECUTION.md) requires a separate exact decision; file-content upload and source handoff use [managed intake](INTAKE.md). Manual Learning and Sources APIs retain their explicit authority checks. Current owned schema is 15.

## Owner experience

Open a model's Teach channel and choose **Set up teaching task**. Choose a configured provider with a current supported price and `task_preparation` purpose. The first cap question is a narrow local exchange: enter an exact USD amount and confirm the displayed provider, scope and limits. No LLM call precedes this authorization. Teaching uses the learning lane; Ask uses its independent interaction allowance.

Describe a desired capability, supplied facts, a correction, or a combination. The provider asks a concise semantic question if bounds, meaning, time, entity, unit or rule-versus-observation intent is missing. A follow-up names its exact pending question. The original objective and every supplied preparation turn remain in the task. Ask-to-Teach transfers preserve the original request/interpretation without acquiring authority or starting work.

A checked proposal displays the requested objective, proposed children, finite interface bounds, source coverage and units, disclosure boundary and total task cap. Natural-language summaries are provider suggestions. Interface descriptions are rendered from checked headers. Exact contracts and proposed acceptance checks are available in **Details**. **Save teaching specification** binds this exact proposal to an owner decision. It saves a prepared task; it does not install vocabulary, source policy or requirements, start acquisition, or publish a model change. An explicit execution decision consumes this retained specification under fresh authority checks. A completed, declined, interrupted or failed preparation needs a new explicit setup for another attempt; no cap refills automatically.

## Representation and local checking

The model-neutral provider wire is `awm-adm-teaching-reply/2`: `profile`, `status`, `message`, and a nullable **native JSON plan object**. A ready reply contains a plan; clarification and unsupported replies contain `plan: null`. The provider schema is closed, acyclic and inlined (6,325 bytes in compact JSON, including source-field descriptions). It requires no recursive-schema capability. The adapter translates its explicit arrays into the existing `awm-adm-teaching-plan/1` representation, then runs the same local checks in the bounded, network-free compute process against the pinned checked snapshot. Neither representation is executable configuration.

The wire plan contains `kind`, `summary`, `types`, `children`, `aliases`, `parameters`, `value_aliases` and `requirements_json`. Each child preserves exact owner input IDs and carries an array of interface headers plus an optional source mapping. Headers name qualified symbols directly; there are no `types`/`functions` grouping objects. `type_id`, `returns_id`, `state_id`, `parameters_id`, and each named parameter's `type_id` refer to the plan's finite type-syntax table. These table IDs are distinct from model declaration symbols. A `ref` type node names an accepted or proposed type declaration through its `symbol` field.

| Type node kind | Active fields besides id/kind |
| --- | --- |
| `bool` | none |
| `int` | `minimum`, `maximum` |
| `enum` | `values` |
| `record`, `sum` | `members`, each with `name` and `type_id` |
| `vector` | `element_id`, `length` |
| `ref` | `symbol` |

Unused scalar fields must be null and unused arrays empty. Duplicate IDs/symbols/parameters, unused nodes, unknown references and cycles are rejected rather than silently merged or repaired. The wire permits at most 128 type nodes, 24 reference levels and 4,096 expansions; decoded local plans also retain the existing document depth/node limits. Local finite-carrier checks still determine whether the headers are supported. Flat vocabulary arrays become the existing checked alias and parameter maps. Aliases name model declarations/modules, not source entities, source predicates or parameter paths.

Source field guidance is shared between the prompt and provider-schema descriptions, with no model-name branch or domain fixture embedded in either. Descriptions explain constraints enforced locally; they do not add provider-side refinements or relax a local check.

| Source field | Required meaning |
| --- | --- |
| `projection.namespace` | Projection namespace; never an implicit prefix for predicates |
| `predicates[].symbol` | Complete qualified name such as `domain.measure`, with at least two dot-separated identifier segments; preserve an existing predicate's exact name |
| `predicates[].kind` | `boolean`, `integer` or `enum`; distinct from the `bool`/`int` spellings in `plan.types` |
| `minimum`, `maximum` | Integer fields; inclusive carrier bounds for an integer predicate. They remain ordered, at most 1,000,000 apart and within the exact safe-integer range. Unused boolean/enum bounds may use the existing defaults 0 and 100 |
| `values` | Empty for boolean/integer; nonempty unique string labels for enum. These define the carrier, not observed facts or stringified integer bounds |

An identifier segment starts with an ASCII letter or underscore, followed by ASCII letters, digits or underscores; a full predicate symbol is at most 200 characters. Enum arrays retain the local limits of 256 labels, each nonempty and at most 200 characters. The adapter never adds a namespace prefix, erases invalid values or changes a carrier to make a proposal pass.

Source mappings use explicit points or bounded, disjoint intervals. Unknown dates require no fabricated `unknown` cell or future interval. Source permissions retain `allow_external: false` until a separate owner decision. Already installed requirements are context, not material to copy into a new proposal. `requirements_json` is null unless new checks are requested; the optional additive policy and individual `value_json` literals retain bounded strict JSON decoding because they use the existing general local policy/value languages. They are small independent fields, never a JSON-encoded whole plan.

Historical prompt contracts `/1` and `/2` retain their strict `status/message/plan_json` decoder. Retained `/3` and current `/4` dispatches accept only native reply `/2`. Prompt `/4` explains source fields in both the instructions and schema descriptions; the provider grammar and local validators are unchanged. Decoder selection binds to retained dispatch provenance, not a model name or a provider-supplied fallback. No historical response is rewritten, repaired or automatically retried. Schema 15, local plan/specification profiles and accepted artifact encodings are unchanged.

| Preparation content | Local boundary |
| --- | --- |
| Intent | `capability`, `facts`, `correction`, or `mixed`; child kinds must match the parent |
| Parent/children | At most four typed children, each retaining exact input-turn references; every input stays linked |
| Interfaces | At most 32 per child; exact type/function/assertion/goal/transition headers, with no bodies, legal/next/cost or arbitrary extra fields |
| Types | Bool, bounded integer, enum, record, sum, vector and existing/proposed type references; each carrier nonempty and at most 65,536 values |
| Scope | Generated acquisition contracts require exactly the proposed interfaces, no helper symbols or retractions, at most 32 declarations and 65,536 bytes per child |
| Corrections | An existing symbol requires explicit correction intent; actual dependency replacement and precedence remain admission responsibilities |
| Vocabulary | Aliases and parameter/value metadata checked against accepted plus proposed headers; no installed vocabulary changes |
| Observations | Source mappings require explicit entities, bounded disjoint time cells, predicates, units and finite value carriers; at most 4,096 entity/predicate/time cells |
| Requirements | Optional additive `adm-conformance` proposals, structurally checked with known required symbols; an existing contract ID cannot be overwritten |
| Unsupported scope | Preparation does not synthesize refined carriers or algebraic presentations. These remain available through explicit local design; the chat profile must narrow or stop rather than fabricate a body |

Proposed requirements are **not independent evidence**. A provider cannot turn its own assertions into owner acceptance authority. They remain `uninstalled_proposal`, requiring separate owner review before installation. Existing owner policy is bound by its digest and remains unchanged. Source permissions likewise remain uninstalled; provider proposals with `allow_external=true` are rejected. A source or quoted message cannot authorize a provider, budget, policy edit or publication.

The specification retains the exact original text, input IDs, Ask gap (if any), complete checked plan, stable child IDs/contracts and checked interface dependencies, context, allowance/price, repair policy and decision. Structural validation is not verified natural-language understanding or a guarantee of learnability. Owner review of intended meaning remains necessary.

## Bounds, accounting and disclosure

A task allowance expires within 15 minutes (or the price expiry, if earlier), has at most six calls, 192,000 reserved input tokens and 49,152 output tokens, 16 child-work records and 12 million work units. Preparation permits at most four input turns totaling 24 KiB. A call has at most 8,192 output tokens, 60 seconds and the existing call-input cap. The monetary cap can stop work earlier. One call and 4,096 output tokens remain held for eventual completion reporting. Execution cannot expand these limits or spend the Ask allowance.

The preparation disclosure covers those explicit Teach inputs, accepted header catalog/vocabulary, installed requirements and source-policy metadata. It excludes other conversations, stored source bodies, result values and credentials. Pasted text in an authorized Teach message is included as untrusted data. Attachment metadata is not file content; attaching metadata never causes extraction.

Two local stages each have at most one million work units and five seconds, further restricted by installation limits. Their combined reservation is established before checking. Provider-call and local-check child identities are separate and durable. Known successful or completed rejected checks settle their measured local work. Interrupted/unknown local work retains conservative reservations; provider usage settles independently from the known call outcome. No provider dispatch is repeated automatically after restart, timeout, malformed output or an unknown outcome. Preparation does not promise to close the knowledge gap within its cap.

## Failure diagnostics

A rejected provider proposal records `failure_code: invalid_preparation` and bounded `failure_diagnostics` on both the task and conversation-work record. The diagnostic identifies the stage (wire, envelope, legacy nested JSON, plan, types, interfaces, input references, dependencies, vocabulary, sources or requirements), a stable reason code and at most eight schema issues with bounded paths. JSON syntax errors include line, column and character offset. Ordinary chat displays the safe stage explanation, states that no model configuration or learning was started, and directs the owner to Details for the exact record. Task summaries expose the same diagnostic through the API.

Diagnostics never include rejected values, arbitrary exception text, provider snippets, credentials or hidden reasoning. Unknown map-key names are redacted in schema paths. Snapshot/context failures and compute exhaustion retain their existing operational handling; exhaustion is not relabeled a provider-format defect. A malformed proposal is rejected as a whole. There is no automatic brace completion, salvage, additional provider call, model switch or budget refill. A failed task needs a newly reviewed explicit setup; the earlier charge and unknown reservations remain part of installation accounting.

## Lifecycle and storage

`preparing → needs_input → preparing → awaiting_review → prepared` is the successful lifecycle. Unsupported, failed, interrupted, declined and stale authority stop preparation. Each exchange has its own durable conversation-work and grant identities. Immutable owner turns and exact proposal digests are retained. Same identity/content replays the original result; changed content conflicts.

The final specification is written only with its accepted decision, task status, terminal work status and event in one ADM transaction. Financial setup uses the existing deterministic decision-intent reconciliation across registry and ADM stores. Restart preserves ready proposals and prepared specifications; unfinished preparation stops without redispatch. Model, support, policy/mode, vocabulary, source-policy, account, spending and provider configuration changes fence prior authority. A historical prepared specification is not evergreen execution permission.

Schema 12 adds `teaching_tasks` and an index. It preserves schema-10 clarification-only consent and schema-11 Ask presentations. Paired backup/restore accepts historical schemas 7–14 and current schema 15; restored remote authority remains disabled. New events are `teaching.prepared` and `teaching.stopped`.

## API

Existing owner-only conversation setup/messages/decisions implement the flow with `purpose: "teach"`. `GET /api/v1/adms/{adm}/interaction-options?purpose=teach` returns usable priced choices. `GET /api/v1/adms/{adm}/tasks?after=…&limit=…` returns bounded summaries; `GET /api/v1/adms/{adm}/tasks/{id}` returns the exact retained preparation/specification. Conversation views include task summaries; Details includes records and accounting. Execution and control use the separate exact commands in [the execution contract](TEACHING_EXECUTION.md).
