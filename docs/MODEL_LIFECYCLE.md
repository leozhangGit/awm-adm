# Model lifecycle and owner controls

Models support naming, empty creation, checked snapshot import/export, independent cloning, conflict-mode changes, archive and durable deletion. All operate within the same local AWM-ADM 0.3.0 service and owned schema 15.

## Using the collection

Create an empty model or import a snapshot file from **Domain models**. Import checks its accepted theory, evidence and owner requirements locally and gives the copy an independent identity. It does not import requests, conversations, live jobs, credentials or proof status. Settings can export a portable model snapshot or create an independent sandbox copy. A whole-service backup has a different purpose: it preserves accounts, model histories, source material, operational records and accounting for recovery.

**Settings** contains a printable model name, conflict precedence and lifecycle controls. Renaming is a compare-and-set operation on the current name; it does not change theory, owner epoch or task authority. Backward mode preserves earlier-arriving conflicting knowledge; forward mode prefers later-arriving conflicting candidates. Both accept nonconflicting learning and enforce the same independent requirements. A switch changes future decisions only and fences prior task authority. Advanced archival retains the model/history and its existing read/export behavior; it does not delete content or implement unarchiving.

Deletion requires an explicit confirmation naming the current model, revision and owner epoch. It is available for active/archived ready models and failed initializations. An initialization still running must finish or fail first; failed models use null revision/epoch bindings. The console explains its scope before accepting the exact name. It retains the submission identity across unchanged retries; the collection exposes operation progress after a lost response or reload. Names and source content are not retained in completed deletion records.

## Durable deletion

The operation progresses through `requested → fenced → draining → purging → deleted`. Recording the request and marking the model inaccessible commit together in the registry transaction. Every subsequent per-model database opening checks the registry under the same application lock. Existing local work cannot publish through that fence or recreate a missing database. Model-scoped reads, requests, event streams, Teach and append operations stop exposing content.

The fencing phase closes model allowances and removes model credential scope. A multi-model read/submit token retains its authority for the other models; a single-model or append token is revoked by removal. Model-scoped compute children are cancelled through their supervisors. Existing task, source, shared-interest and candidate records belong to the instance database and are removed together. Independent copies have their own identity and remain usable.

Draining removes registry payload references. Known accounting remains; ready/leased work which has not crossed gateway authorization can release its reservation. A dispatched or uncertain call keeps its full unresolved reservation until identified usage is received. Deletion neither retries a call nor invents usage. A late result is reduced to accounting metadata and never enters a model inbox or restores its theory. An administratively discarded successful provider response is recorded as `failed / model_deleted` with its actual usage, without retaining its output text.

Purging unlinks the owned SQLite database and its WAL, shared-memory and rollback-journal sidecars, then synchronizes the directory. Cleanup is constrained to server-generated instance paths; unexpected symlinks or file types block it. Interrupted cleanup resumes from the durable stage. A failure enters `blocked` with the original operation and resume stage; an explicit version-bound retry continues the same operation. It never reactivates the model.

The gateway receives bounded, idempotent redaction instructions for the model's grants through its authenticated synchronization channel. It replaces prompt/result payloads with a lease-only delivery record and sanitized accounting, and records a durable tombstone even when a grant never reached the gateway. The tombstone prevents a delayed request from reintroducing content. Finishing an already in-flight provider call also applies the redaction rule. Acknowledgements survive loss by replaying the same cleanup instruction.

Local model content can be purged while the gateway is unavailable or usage remains uncertain. The operation stays in `purging` until gateway payload cleanup is acknowledged; the UI identifies that wait. **Unknown usage does not block completion**, because only payload cleanup acknowledgement is required, not a provider response or invoice. A stopped gateway therefore needs to be started to complete its storage cleanup; no provider call is made by cleanup.

## Content inventory and retained records

| Location | Deletion action | Retained scope |
| --- | --- | --- |
| Instance SQLite database and sidecars | Remove all accepted versions, policies, evidence, snapshots, sources, uploads, conversations, tasks, drafts, requests, results, events, feeds, interests and candidate records | None in active instance storage |
| Registry `instances` | Clear name; retain inaccessible deleted identity | Opaque model ID and deletion status |
| Registry `operations` | Erase model-associated import/export bodies and cached snapshots/results; fence late exports | Operation ID, replay key/digest, kind and deleted status |
| Registry `credentials` | Remove target model from multi-model scope; remove target-only/append credential | Other-model authority only |
| Registry `source_arrivals` | Remove the model's receiver payloads | None |
| Registry `allowances`, `budget_children` | Close model allowances, remove child references and redact scope/replay labels | Original numerical cap, price, identity and charge totals; no resumed authority |
| Registry `grants`, `charges`, `legacy_spending` | Erase wire, task/provenance and provider-output payloads; detach episode references | Opaque dispatch/model IDs, settlement lease, provider/configuration/price IDs, original token/call/time bounds and exact known/unknown accounting |
| Registry `deletions`, `deletion_grants` | Retain bounded content-free reconciliation/replay records | Stage/version, generated file inventory, confirmation digest, gateway acknowledgements |
| Gateway `dispatches`, `redactions` | Remove prompt and output; retain at-most-once tombstone and accounting delivery | Grant ID, digest, lease, status, times and sanitized usage |
| Shared provider connections, installation accounts and prices | Preserve | Independently owned installation configuration |
| Other models and snapshot copies | Preserve | Their independent knowledge/history |
| Downloaded exports, external backups, third-party provider storage | Outside active-instance deletion | Deletion makes no claim to erase these copies |

The application and gateway use SQLite. Logical deletion is not secure media erasure: free pages, filesystem snapshots, transient process memory and external backups can retain historical bytes until their own lifecycle ends. The gateway cannot retract material already sent to a provider. No broad disk cleanup or provider-side deletion is implied. Browser outbox entries for the target are cleared in the participating console; already exported or independently retained client copies are outside the server's control.

## API and recovery

All new controls are owner-only and use the existing session/CSRF boundary:

- `PATCH /api/v1/adms/{adm}/name`: current `expected_name` and replacement `name`.
- `DELETE /api/v1/adms/{adm}`: stable `idempotency_key`, `expected_revision`, `expected_epoch`, exact `confirm_name` and `confirm_delete: true`.
- `GET /api/v1/deletions`: bounded pages (default 20, maximum 100). `scope=active` or `all` advances `after` in ascending insertion order; `scope=completed` returns newest first and advances `after` toward older row IDs. The console polls active work and the 20 latest completed operations without loading all historical tombstones.
- `GET /api/v1/deletions/{operation}`: content-free progress, inventory and gateway wait.
- `POST /api/v1/deletions/{operation}/retry`: exact `expected_version` for a blocked operation.

An identical delete retry returns the original operation even after purge; a changed meaning under the same key fails. A second identity for an already-deleting model cannot create another cleanup. Old model routes return `410 gone` where a valid model-scoped operation reaches the fence; revoked credentials fail authentication/authorization first. Invalid route inputs can fail schema validation before resource lookup. Old global import/export operation views stop returning deleted content immediately.

Schema 15 adds registry `deletions` and `deletion_grants`. The gateway adds its own idempotent redaction table without changing credentials or key material. Startup does not reopen deleting models. Paired backup/restore preserves deletion progress, minimal tombstones and all retained uncertainty; restored spending and client authority remain disabled. An older external backup is an independent copy and can restore knowledge that was present when that backup was captured.
