# Conversation and task contracts

These contracts describe the administrator, financial and conversational resources of AWM-ADM 0.3.0. Current storage schema is 15. Versioned routes and serialized identifiers are compatibility contracts. [OpenAPI](../contracts/openapi.json) specifies actual inputs; [`contracts/workflows/`](../contracts/workflows/) contains independent finite specification oracles, not runtime authorization code.

## Identity and authority

Each resource has an opaque server identity and an ADM scope where applicable. Revision, theory/support roots, owner epoch, source-policy and vocabulary generations bind meaning. Task/proposal digests refer to retained validated artifacts; possession of a digest alone grants no authority. Timestamps are integer UTC milliseconds and money is integer micro-US dollars.

| Resource | Binding |
| --- | --- |
| Conversation and input | ADM, Ask/Teach channel, owner turn, selected attachment IDs and current context |
| Question/proposal | Triggering input, exact proposed meaning, context, payload digest and finite expiry |
| Decision | Authenticated owner, exact proposal/context/digest, idempotency identity and accept/decline |
| Allowance | Owner-chosen scope, exact provider/configuration/price, lane, finite dollar/call/token/work caps and expiry |
| Teaching specification | Immutable checked goal/interfaces/children/disclosure; no execution authority by itself |
| Execution/review | Exact specification, retained version/context, parent fence and candidate digest when reviewing |
| Presentation | Original request/result or task subject, exact context and supported narrative references |

LLM output, source documents, attachments and ordinary chat cannot select their own authenticated principal, change protected settings, issue grants or confer publication authority. An ambiguous reply can create a clarification or proposal; a generic yes to an expired/unrelated proposal is not acceptance.

## Roles

The owner can manage accounts, models, spending and exact decisions. Scoped read/submit clients retain only explicit model API permissions. Append clients can push bounded source items to named scopes and inspect their acknowledgments; they cannot read the model or choose providers, alter policy, fund work or publish. Worker and gateway credentials have separate private roles. Public owner-token compatibility ends after administrator setup.

## HTTP families

| Paths | Purpose |
| --- | --- |
| `/api/v1/auth/*` | Local setup, password sessions, recovery and CSRF metadata |
| `/api/v1/spending`, `/prices`, `/allowances` | Owner financial configuration and conservative reservations |
| `/api/v1/adms/{adm}/conversations/*`, `/decisions/*` | Durable scoped messages and exact owner decisions |
| `/api/v1/adms/{adm}/tasks/*` | Checked preparation, execution, review and time-only renewal |
| `/api/v1/adms/{adm}/attachments/*`, `/intake/*` | Immutable supplied material and managed source intake |
| `/api/v1/adms/{adm}/name`, `/api/v1/adms/{adm}`, `/deletions/*` | Naming and durable deletion |
| `/api/v1/*` | Existing explicit model/query, preview, learning, source/feed, snapshot and operational resources |

The table groups route families; use OpenAPI and the feature guides for exact endpoint spelling and closed request models. Model operations, grant identities and old idempotency values are not reinterpreted to create broader chat permission.

## Persistence and recovery

Immutable turns, questions, proposals, decisions, work and outcomes persist in per-model stores. Registry reservations and per-model work use durable handoff intents across separate transactions. Same identity with changed meaning is a conflict. Restart reconciles acknowledgments and retains uncertain calls without automatic dispatch.

Backup/restore preserves supported schema-7–15 content while disabling remote financial authority and revoking operational credentials. Startup migrations are transactional per owned database and reconcile the installation before dispatch. Unknown or foreign stores are refused; missing established state is not silently adopted as empty.

## Disclosure and presentation

Owner setup explicitly permits bounded input/catalog/user context and, separately, outcome narration. Attachments and evidence excerpts require their own disclosure. Existing preview consent does not gain result/source disclosure implicitly. Keys, account secrets, other models' conversations, hidden provider reasoning and unrestricted logs are excluded.

Main chat uses readable outcomes; Details provides exact technical artifacts. Readiness reasons are application-authored and checked before work and again at dispatch. Tab-local drafts do not authorize work. Provider narration is fallible; checked local results retain independent bindings and labels.

See [Conversations](CONVERSATIONS.md), [Ask](ASK.md), [Teaching](TEACHING.md), [Execution](TEACHING_EXECUTION.md), [Intake](INTAKE.md), [Limits](LIMITS.md) and [Model lifecycle](MODEL_LIFECYCLE.md).
