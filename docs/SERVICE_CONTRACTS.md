# Service and data contracts

AWM-ADM 0.4.0 combines a domain-agnostic finite library, persistent local runtime, login-free local APIs, conversations, bounded learning and source intake. This document defines their shared boundaries. [Architecture](ARCHITECTURE.md) identifies component ownership; [OpenAPI](../contracts/openapi.json) and [generated schemas](../contracts/schemas/) define exact implemented transports. A valid JSON shape does not confer semantic or publication authority.

## Model identity and persistence

An `adm_id` identifies one independent domain model, distinct from an external provider's model name. Every request, task, source, candidate and authorization decision is scoped to its receiving ADM. Shared connections and processing interests do not merge models or create a global conflict order.

The application owns a registry and a SQLite database per ADM. A publication transaction commits the accepted theory, support, candidate decision, relevant parent state and events within that ADM's store. Registry, gateway and model databases use separate transactions. Durable intents and idempotent reconciliation connect those boundaries; they are not a distributed atomic commit.

| Identity | Meaning |
| --- | --- |
| ADM / conversation | Independent model and a scoped Ask or Teach history |
| Request / attempt / result | Retained intent, one execution, and its bound outcome |
| Theory root / revision | Executable content and a durable model-state view |
| Support root / source-policy generation | Evidence support and permission/coverage context |
| Owner epoch | Requirements and conflict-policy authority |
| Source version / span | Immutable input bytes and the exact cited passage |
| Candidate / receipt sequence | Complete proposed change and receiver-local admission order |
| Task / child / grant | Parent work scope, one bounded step and one provider-dispatch identity |
| Historical price / allowance / charge | Preserved prior valuation and settlement; no gate for new work |

These identities are not interchangeable. Same identity with different submitted content is a conflict; an unchanged retry retrieves existing work rather than authorizing another paid call.

## Local requests and authoritative results

Supported requests execute against a checked, pinned local model. Interpretation or an explanation from a provider is not a local result. The finite engine supports bounded evaluation, Boolean claims, planning, certificates and result inspection; the source layer also supports exact historical fact lookup.

An answer retains its query, theory, support, owner context, request and attempt bindings. A new admission does not rewrite historical results. Planning reports distinguish witness validity, shortest action count, depth-bound exhaustion and reachable-graph exhaustion. Resource exhaustion is inconclusive rather than proof or a promise that learning will help.

A genuinely unsupported capability can remain a durable learning gap. Creating a gap alone does not issue provider authority. Background acquisition and local serving use separate bounded capacity; queueing a job does not establish that a worker is executing it.

Real Lean checks report `lean_kernel` separately from `exhaustive_finite` correspondence to executable representations. Certificates are derived for the exact current theory and action scope. Neither a snapshot nor provider output imports trusted proof status. The interpreter and translator remain trusted code. See [Engine](ENGINE.md) and [API](API.md).

## Knowledge admission

Each ADM begins empty or with a locally rechecked snapshot. Domain rules and data belong to that instance; the reusable engine has no equipment, inventory or permissions solution built into it.

Learning follows proposal, checking, bounded diagnostics and revision. Incomplete private constructions never serve requests and never enter the complete-candidate inbox. A complete candidate receives a monotonic local receipt sequence at the receiving ADM. Required review can hold the head of that queue while serving continues against accepted knowledge.

- **Backward mode:** an earlier accepted conflicting result retains precedence; the later conflicting batch is rejected.
- **Forward mode:** a later admissible conflicting result may replace the earlier one. Dependency checks retire or replace affected conclusions.
- **Both modes:** enforce finite semantics, exact dependencies, source support and independently installed owner requirements. Review approval permits checking; it cannot bypass these checks.
- **Mode changes:** apply to future decisions and advance the relevant authority context. They never replay earlier conflict decisions automatically.

Individually valid candidates need not be jointly valid. Publication checks the candidate against the current accepted state and fences cancellation, expiry, stale context and deletion. Finite task limits bound effort; they do not guarantee acquisition of the requested capability. See [Learning](LEARNING.md), [Teaching](TEACHING.md) and [Execution](TEACHING_EXECUTION.md).

## Conversations and automatic execution

Ask and Teach have separate durable streams. Ask checks a provider interpretation, executes supported meaning locally and labels any provider explanation separately. Teach validates finite specifications and automatically starts clear local requests. It asks only for uncertain meaning or a necessary protected decision. Neither source material nor provider output can install owner requirements or override policy.

Bounded owner context is managed automatically. Accepted theory is independent of chat prose. Uploads are disclosed only when selected in a submitted Teach request. Model, connection, policy and cancellation bindings are checked again before work and publication. Human clarification waits do not expire financial authority because there is no financial authority setup. See [Conversations](CONVERSATIONS.md) and [Chat contracts](CHAT_CONTRACTS.md).

## Provider dispatch and accounting

One configured connection is enabled after its successful test. Interpretation, acquisition, extraction and narration use that configuration without purpose permissions or monetary limits. Exact grant purpose/payload/version, finite execution bounds, authenticated leases and at-most-once dispatch remain mandatory.

The gateway records an identity before outbound dispatch. Repeating it returns retained state; an unknown dispatched outcome is never automatically repeated. Known input/output tokens, including failures, contribute to usage charts. Missing or unverified-zero usage remains explicitly unresolved. Historical priced records retain their valuation and settlement history but do not gate new calls.

Provider choice does not select task semantics or relax admission. Guidance remains model-neutral and authored schema property order is preserved; accepted artifacts retain canonical encoding. See [Connection](CONNECTION.md) and [Limits](LIMITS.md).

## Supplied evidence and managed intake

Sources retain immutable versions, original bytes, typed metadata and exact extraction spans. Receipt means material was stored, not that a fact was accepted. Extracted claims are proposals. Owner source policy governs permitted predicates, entities, units, carriers and temporal coverage; source content cannot define its own authority.

Finite projection checks schema/carrier membership, source references, units, effective intervals, conflicts, owner requirements and bounded size. Admission publishes executable content and its evidence support together. Absence is not automatically false. A date or entity outside supported coverage returns `needs_input` rather than an invented value.

Historical requests support exact instants (`lookup_fact`) and half-open UTC periods (`lookup_fact_period`). Period answers require complete unique active interval coverage with equal computed values, value kinds and units; point-only evidence, gaps, overlaps and disputes cannot establish a period-wide value. A value change asks for a narrower time. Automatic Ask resolves civil-date boundaries using an explicit relevant zone or its captured system default. Query/result bindings retain the entire resolved scope. See [temporal interpretation](TEMPORAL_INTERPRETATION.md).

Historical intervals remain distinct from receipt order. Two capacities for different years can coexist. Conflicting claims for the same resolved interval follow ordinary review and forward/backward admission. A superseding correction can hold dependent current answers before replacement learning; historical results keep their original bindings and provenance.

Managed intake provides bounded push queues, receipts, throttling, finite processing reservations, pause/resume and fair scheduling. Append credentials can submit only to their named scope and inspect acknowledgments; they cannot read models, choose providers, change policy, fund work or publish. No Slack crawler or other pull connector is implicit. See [Sources](SOURCES.md), [Feeds](FEEDS.md) and [Intake](INTAKE.md).

## Access, snapshots and deletion

The supported installation has one trusted local workspace. Public console/API access needs no login. Same-origin/Host/peer checks bound that access; private operator/worker/gateway channels retain separate machine credentials. The fixed provider gateway is the only provider-egress path; source/query data cannot select arbitrary destinations.

Model snapshots contain accepted executable knowledge, owner requirements, necessary evidence and optional typed state. They exclude accounts, credentials, live grants, conversation/task queues and imported proof authority. Import validates the package and creates an independent identity. Operational backup is a different process.

Named deletion fences access and publication before durable cleanup. It preserves uncertainty accounting and a content-free replay tombstone; it does not delete independent clones, shared connections or separately held backups. Interrupted cleanup remains fenced and can resume. See [Local access](LOCAL_ACCESS.md), [Security](../SECURITY.md) and [Model lifecycle](MODEL_LIFECYCLE.md).

## API and operational boundaries

Model creation commits its reservation and operation link in one transaction. Failure receipts preserve safe application-authored causes without exposing raw exception text. A failed creation is distinct from pending work; explicit retry is available only when the service confirms no allocated model or unresolved legacy orphan reservation. Polling and repeated reads do not create a new attempt. The plugin retains the failed receipt and uses one durable replacement intent for each user-directed retry.

The unified `/api/v1` API exposes models, local requests, interpretation previews, learning, sources/feeds, snapshots, events, diagnostics, connections, direct Ask/Teach exchanges, attachments, managed intake and lifecycle controls. Manual preview history uses `interpretation-sessions`; Ask/Teach uses `conversations`. URL versioning is independent of serialized profiles and storage formats. Use [API](API.md) and [OpenAPI](../contracts/openapi.json) for exact methods, pagination and permissions.

Paired backup/restore is an **offline operator CLI**, not a public backup HTTP endpoint. It locks both stopped storage owners, checks schemas and hashes, and restores only into a fresh destination. Supported operational restore preserves knowledge/history and uncertain accounting while revoking operational credentials, disabling remote authority and pausing feeds. An old backup cannot reconstruct later external expenditure.

The runtime has one storage-owning application, bounded local children, a learning worker and a private provider gateway. SQLite uses local volumes and short transactions. Durable histories have finite caps; automatic evidence-graph deletion is not implemented. Explicit event pruning preserves a resynchronization floor and does not delete the authoritative result/evidence records.

The service computes model-relative answers and plans. It does not execute physical actions, transfer resource rights or implement clustered Byzantine coordination. See [Runtime](RUNTIME.md), [Operations](OPERATIONS.md) and [Release scope](RELEASE.md).
