# Conversation and task contracts

AWM-ADM 0.4.0 exposes direct Ask/Teach exchanges under `/api/v1`. The current operational storage schema is 17; core artifact and snapshot formats are unchanged. [OpenAPI](../contracts/openapi.json) specifies the request shapes.

## Meaning and authority

| Resource | Binding |
| --- | --- |
| Exchange | ADM, Ask/Teach channel, local input, selected attachments, origin and current context |
| Clarification | Exact preceding exchange and unresolved question; a reply is checked against current context |
| Teaching specification | Checked intent, finite interfaces, children, selected evidence and task-owned acquisition contracts |
| Execution | Exact specification, current revision/requirements, parent cancellation fence and receiver receipt order |
| Presentation | Original request/result or task, exact context and locally supported explanation references |
| Provider grant | One call identity, exact connection version, purpose, payload and finite execution limits |

A clear local Teach submission authorizes automatic checked learning. This authority comes from the application accepting the request, never from provider output or an attachment. Provider-proposed owner requirements cannot install themselves. Ambiguous requests ask a question; ordinary clarification has no financial expiry. A model/configuration change still requires checking meaning again.

Ask is read-only model use. It cannot silently create a teaching task. A provider interpretation is checked before local execution; a provider explanation cannot replace or upgrade a local outcome. Accepted theory is independent of chat history.

Clear references in linked owner messages resolve conversational inputs without routine confirmation. Explicit current inputs override earlier scenario values; unrelated subjects, conflicting references and genuinely absent values require clarification. Reported unresolved assumptions still block execution. Interpretation remains fallible even when its command is well typed.

Successful simple results use conversational explanations with independently generated compact outcome labels. Historical values carry a Historical evidence qualifier; partial teaching, missing/disputed evidence, within-period changes and execution limits remain visible. Shared [meaning and representation rules](TEMPORAL_INTERPRETATION.md) supply a captured system timezone without per-question setup. Full summaries and exact bindings stay in the API; a compact label does not validate the explanation's prose. Narration receives only the current question and bounded owner context already selected for the exchange, alongside its checked outcome.

## Context and disclosure

The service selects bounded prior owner turns and exact result references from the same model/channel. Unrelated API calls, other models, assistant prose and unselected files are not silently added as premises. Teach includes the original bytes of explicitly selected attachments in preparation; uploading alone does not disclose or teach them. Source extraction uses the checked task's selected source scope. No credential, unrestricted log or hidden provider reasoning is included.

Each durable exchange has an idempotency identity. Replaying unchanged input returns the same work; a changed body under that identity conflicts. An idle user question does not authorize repeated calls. Active execution retains finite call duration, attempts, no-progress stopping and compute/storage limits.

## Access and recovery

The console and retained public APIs use a login-free trusted local workspace. Clear Teach requests authorize only their expressed learning intent; Ask does not implicitly teach. Provider and source text cannot change independent requirements. Append credentials constrain their ingestion endpoint; they do not isolate an otherwise trusted local process from the shared public API. Worker and gateway machine credentials remain separate.

Turns, questions, tasks and outcomes persist. Registry, model and gateway handoffs use durable intents rather than an assumed cross-database transaction. Restart retains accepted knowledge and known outcomes; uncertain provider dispatches are never automatically repeated. A paired restore disables the connection, pauses feeds and revokes operational credentials. Historical financial records remain inspectable but do not gate new exchanges.

The console shows readable outcomes and progress. Exact technical artifacts remain in login-free local APIs for investigation, without routine setup or Details panels. See [Conversations](CONVERSATIONS.md), [Ask](ASK.md), [Teaching](TEACHING.md), [Intake](INTAKE.md) and [Limits](LIMITS.md).
