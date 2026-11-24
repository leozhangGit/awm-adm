# Attachments and managed source intake

Teach turns explicitly supplied material into checked finite facts. Original bytes, versions and cited spans remain distinct from accepted model knowledge. The provider proposes mappings and claims; local projection, evidence and admission checks determine what can publish.

## Teach with material

Attach or select retained Markdown, UTF-8 text, JSON or JSONL and describe what the model should learn. Uploading only stores the original. Sending the Teach request authorizes its selected material for preparation and extraction. A clear request proceeds through checking and admission automatically. Unclear entities, units, dates, finite bounds or rule-versus-observation intent produce a clarification.

A checked task can contain separate capability and source children. Preparation proposes one explicit shared temporal evidence catalog for all selected source material, with separate material selections per child. The service expands that mapping without merging different projections or changing their meaning; source-policy, finite-carrier, temporal-meaning, original-span and admission checks apply. An allowed entity/predicate/time combination is not evidence that a value exists there. Source mappings must identify actual selected material. Pasted material and files can be selected together through the service-owned preparation manifest. Each selected message retains its exact original turn origin and bytes; successive messages in one explicit lineage share a source collection. Child input links include instructions, while `material_ids` select only originals that supply facts. The provider cannot invent source IDs, permissions or evidence groups. A URL inside text remains a citation, not a fetched source. Preparation and ingestion use the same checked material resolver; invalid references are preparation failures, not requests for users to construct mappings. Preparation cannot install provider-authored behavioral requirements. The task establishes source permissions for its checked scope; additive coverage preserves existing carriers and provenance. Unclear meaning requires clarification. An unsupported coverage transformation is reported as unsupported; it never silently redefines accepted evidence. The [temporal contract](TEMPORAL_EVIDENCE.md) defines mixed scopes, legacy coexistence and bounded collection queries.

Extracted assertions must satisfy exact evidence references, typed values, units, temporal cells and source policy. An invalid assertion holds the whole item. Checked admission obeys receipt order, forward/backward precedence and independent requirements. Automatic checking is recorded as automatic Teach authority, not fabricated human review. Completion lists accepted and unresolved children separately.

Retained originals survive reload and may be selected again. Removing a composer attachment does not delete its stored original. Identical re-upload deduplicates; a same-named changed file can propose a correction to its current source version. Upload alone does not activate the correction.

## Managed push queues

Normal Teach is a finite task. An integration needing ongoing intake uses local `POST /api/v1/adms/{adm}/source-queues` with the same direct-message input and an explicit source-only request. This is a bounded queue of supplied material; no crawler or pull connector is created. Preparation checks finite entities, predicates and coverage before the queue becomes available.

The task owns its feed. Its commands can pause, resume, cancel or finish receiving. Pause preserves received data while fencing new dispatch/publication. Finish freezes the source sequence and drains already received items within remaining operating limits. Cancel preserves accepted knowledge and unresolved usage. Direct feed controls cannot bypass a managed parent's authority.

Local callers can push to the prepared queue without a credential; task/source scope, throttling, idempotency and publication checks still apply. A local caller can optionally issue an append credential at `POST /api/v1/adms/{adm}/intake/{task}/credentials`. The credential binds one ADM/task/source scope and expires no later than the task. It permits bounded pushes and receipt reads only. The append endpoint cannot read the model, choose a provider, change policy or publish. This is an endpoint capability; it does not isolate a process that also has access to the full trusted local workspace. The secret is returned once.

Producers send `AppendInput` to `POST .../intake/{task}/push`: a durable idempotency key and up to four records with source/item/version, UTF-8 content, media type, attribution and an optional exact superseded version. Provider or policy fields are forbidden. Receipt and original storage commit together. `202` means received, not learned. A lost acknowledgement is recovered by replaying the identical body/key or reading `GET .../intake/{task}/receipts/{key}`; changed content under that key conflicts.

[`scripts/push_source.py`](../scripts/push_source.py) is a small producer client using a privately supplied append token. It refuses remote plaintext HTTP and redirects, creates no authority and makes no automatic retry. Throttling/backlog responses require backoff; stale scope or credentials require owner attention. A new acknowledged batch must not be invented merely because a response was lost.

## Operating bounds

| Dimension | Bound |
| --- | --- |
| Original | 256 KiB UTF-8; supported `.md`, `.txt`, `.json`, `.jsonl`; no NUL or path-bearing filename |
| Retained uploads | 100 originals / 8 MiB encoded records / 1,000 submission identities per model |
| Push | At most four items; ordinary HTTP and batch bounds apply |
| Pending managed intake | 100 distinct originals / 8 MiB per model, including paused queues |
| Producer rate | 60 items per minute per credential and model |
| Feed | Four pending processing items; at most 20 items per standing task; one-item scheduling turns |
| Task | Finite call/token/local-work/child reservations; no dollar cap or price dependency |
| Local phase | At most one million work units / five seconds; source processing reserves its phases before work |
| Completion | Bounded explanation separate from the deterministic accepted/unresolved outcome |

A retained file can exceed the configured request capacity. Storage acknowledgement does not guarantee extraction or eventual acceptance. Conservative work reservations and no-progress stopping can end a queue before its item maximum. Separate serving capacity remains available. Unknown provider outcomes are retained and never automatically dispatched again; reprocessing is a new explicit task.

## Corrections and recovery

Source receipt order, event time and candidate arrival order are different. Storing an explicit correction atomically holds dependent current support. Fresh lookup then returns `needs_input` until replacement evidence is admitted; historical results retain their original bindings. Forward mode permits admissible later replacements; backward mode keeps earlier conflicting knowledge. Neither source supersession nor automation bypasses precedence or owner requirements.

Task-owned source-policy/support commits advance that parent's bindings atomically. Other changes fence it rather than silently adopting new meaning. Resolution records bind the replacement revision and claims without rewriting historical notices. Evidence retained in snapshots is rechecked on import.

Owned schema 18 preserves source/intake stores, direct exchange metadata and immutable historical actor references. Recovery preserves originals, cursors, known outcomes, accepted facts and unresolved dispatch records. Paired restore disables the connection, pauses feeds and revokes credentials. See [Sources](SOURCES.md), [Feeds](FEEDS.md), [Teaching execution](TEACHING_EXECUTION.md) and [Operations](OPERATIONS.md).

One-shot clarification continuations use the [selected-material packet](SOURCES.md#clarification-packets) for their source child. The packet contains the explicitly selected originals and the child's linked textual replies, within existing byte/input limits. One extraction can therefore interpret their combined meaning. Ordinary single-message tasks and standing queues keep their per-item behavior. Failures retain [structured source diagnostics](PROVIDER_FAILURES.md#source-completion-diagnostics).
