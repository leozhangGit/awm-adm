# Operations and recovery

AWM-ADM is a bounded, single-owner, single-host service. This guide covers the Linux ARM64 Docker profile, offline service recovery, observability and retention. Model export, service backup and operational rollback have different meanings. The owner controls all three.

## Recovery artifacts

| Artifact | Includes | Purpose and authority |
| --- | --- | --- |
| Model snapshot | Accepted executable content, owner policy, necessary support and optional typed state | Creates an independent ADM with fresh identity after local validation. No provider credentials, jobs, grants, sessions or imported proof authority. |
| Service backup directory | Registry, all registered ADM databases, encrypted gateway vault and dispatch ledger, ownership markers, file hashes and version | Recovers an installation at a coordinated stopped point. Contains private knowledge and operational records; keep it private. |
| Separately secured recovery material | Matching gateway master key, owner/worker/gateway tokens, static provider keys if used, effective configuration, Compose overrides and image identity | Needed to decrypt the vault and reproduce the deployment. Never place these values in diagnostic reports or verification artifacts. |

The backup CLI does **not** decrypt or include key files. The gateway database contains encrypted credentials and an encrypted sealing key. Losing the matching master key means those credentials cannot be recovered. A newly generated key cannot decrypt an old vault. Restore the original key from secure recovery material, or retain the old vault offline and create new provider connections in a separately initialized installation. Never reset a dispatch ledger to make an uncertain call retry.

Backups are private directories, not encrypted archive files. Hashes detect accidental modification; they do not authenticate a bundle against a hostile local administrator. Use trusted local storage and a separate encrypted backup destination as required by the owner. Do not share recovery bundles as diagnostic reports.

## Capture a consistent backup

From the AWM-ADM directory, use the same Compose project and overrides as the running service. The commands below assume the default `awm-adm` project. Choose a new backup name each time.

```sh
mkdir -p .local/backups
chmod 700 .local/backups
docker compose stop
docker compose run --rm --no-deps operations backup \
  --app-data /var/lib/awm-adm \
  --gateway-data /var/lib/awm-gateway \
  --output /backups/before-upgrade
docker compose run --rm --no-deps operations verify-backup /backups/before-upgrade
docker compose up -d --wait --wait-timeout 60
```

On native Linux, the backup directory must also be writable by UID/GID 10001; provision that ownership before running the container. Docker Desktop supplies its own bind-mount permission mapping.

The `operations` service is a short-lived tools-profile process with no network, no secret mounts, no published port and only the app/gateway data volumes plus the backup destination. It acquires **both** existing process-owner locks before reading. A running app or gateway makes capture fail. The worker must also be stopped operationally; it has no database to capture. SQLite's backup API includes committed WAL content. Each copied database receives an integrity/application-ID/schema check. The bundle is staged privately, flushed and renamed only after all files and its manifest exist. An error before publication leaves the original stores intact and no completed bundle. If the final directory flush fails after rename, the command can report failure while a valid destination exists; inspect and verify that destination before retrying, and never overwrite it. A process killed during staging may leave a `.awm-recovery-*` directory; it is not a valid published backup and can be inspected/removed while no operation uses it.

Current capture is schema 15; verified bundles from owned schemas 7–14 also support restore and subsequent startup migration. The envelope is at most 1,003 files and 6 GiB of logical database content. Larger configured installations need a separately tested backup envelope. Symlink paths, foreign databases, missing established stores, unregistered databases, unsupported schemas and existing destinations are refused. Do not copy just a running SQLite main file. Backup may take time proportional to retained storage; it is an offline operation without a serving-availability guarantee.

On native installations the equivalent command is `awm-adm operations backup --app-data APP_ROOT --gateway-data GATEWAY_ROOT --output NEW_DIRECTORY`, with both storage owners stopped. Local file paths are operator arguments and never accepted through the public API.

## Restore into a fresh destination

Keep the original deployment stopped when replacing it. Never run an original and its recovered copy as independent continuations of the same operational history. Use model export to create a genuinely independent ADM.

```sh
docker compose stop
docker compose run --rm --no-deps operations restore \
  /backups/before-upgrade --output /backups/recovered
```

Restore verifies the full inventory and digests before writing to a **new** directory. It does not overwrite volumes. The output contains `app/`, `gateway/` and `restore.json`. To run this directory, use a separate override file such as `.local/recovery.compose.yaml`:

```yaml
services:
  app:
    volumes:
      - ./.local/backups/recovered/app:/var/lib/awm-adm
  provider-gateway:
    volumes:
      - ./.local/backups/recovered/gateway:/var/lib/awm-gateway
  operations:
    volumes:
      - ./.local/backups/recovered/app:/var/lib/awm-adm
      - ./.local/backups/recovered/gateway:/var/lib/awm-gateway
```

Paths resolve relative to the first Compose file. Preserve any effective port/configuration overrides and ensure directories are writable by container UID/GID 10001 on Linux; Docker Desktop handles its bind-mount mapping. Verify the merged configuration with `docker compose -f compose.yaml -f .local/recovery.compose.yaml config` before startup. Start with those same files and the matching master key. Keep the original volumes and backup until recovery is validated.

Recovery intentionally changes operational authority while preserving accepted theories and historical results:

- Disable global remote calls and advance their authority generation, even when configuration would enable a fresh installation.
- Revoke persisted sessions and scoped API tokens. Restoring an account-bearing bundle also revokes outstanding reset/setup credentials and advances the administrator generation. Sign in with the restored password or use [local operator recovery](ADMINISTRATOR.md); a schema-7 restored copy establishes its administrator after migration. Issue new scoped tokens deliberately.
- Pause every feed and advance its generation. Resuming is an explicit owner action against current state.
- Clear component leases. Startup gives new app/component generations and reconciles interrupted local requests, episodes and receipts through the ordinary recovery path.
- Mark captured ready/leased/dispatched app grants as `outcome_unknown`, retaining their reservations. A ready grant in an old backup cannot prove it remained undispatched in the abandoned timeline.
- Preserve gateway dispatch identities. Captured unfinished dispatches become unknown; the same identity never triggers a second call.

A backup cannot contain calls, facts or revocations that occurred **after** it was captured. `restore.json` explicitly labels post-backup external usage unknown. Before enabling remote work, the owner must reconcile the abandoned timeline with provider records and retained newer ledgers, or keep remote work disabled. The service does not claim a rollback can reconstruct missing provider expenditure or silently reset a budget. A completed old result remains historical; it does not authorize external actions.

Check identities, accepted/support roots, policies, selected results, pending status, feed cursors and usage before resuming. Test a supported local request with remote calls disabled. Static secrets require their original separately mounted files; managed credentials require the matching vault key. Wrong/missing key is a gateway startup failure, while local ADM operation remains independent.

## Upgrade and failure recovery

Only owned schemas 1–14 migrate to schema 15; foreign operational stores and future schemas are refused. Supported model snapshots are rechecked through model import, not database adoption. Migrations use one transaction per database. A migration failure rolls that database back; a service contains multiple databases, so an upgrade is not a single cross-database transaction.

Before upgrading, capture a current service backup and record the previous image/configuration identities. Test the upgrade on a recovered copy. If startup or verification fails, stop all components and restore the pre-upgrade bundle into new paths using the matching supported version. Do not start an older binary on a partly migrated directory or edit `user_version` to bypass checks. Preserve the failed directory for diagnosis. There is no automatic destructive downgrade.

For disk exhaustion, stop the workload, check free space inside Docker as well as on the host, and preserve the affected stores. Increase capacity or remove only identified disposable artifacts; never delete user volumes to repair storage. SQLite transactions roll back failed writes, but arbitrary filesystem/device corruption is outside that guarantee. Restore space, run the offline backup/integrity checks, and restart. Existing durable recovery fences apply; failed/unknown provider outcomes do not automatically retry.

Completed source jobs and projection decisions retain their original generation/deadline fields across restart. Only resumable queued or review-pending feed work receives a fresh lease; interrupted or uncertain provider work remains stopped and cannot be redispatched automatically.

App SIGKILL, child time/resource exhaustion and expired component heartbeats are explicit failure cases. Local request interruption is inspectable and requires a deliberate retry when interrupted. A stopped provider gateway does not stop supported local serving. Compute deadlines use monotonic time. Receiver sequence numbers determine admission order. Provider quota accounting has a persisted high-water clock and retains unresolved calls beyond periods; wall-clock changes can still shorten/extend wall-clock credential/lease lifetimes. Keep host time synchronized. No clock-based guarantee establishes external truth.

## Metrics and bounded diagnostic export

The owner console's **Operations** view retrieves `/api/v1/operations/diagnostics` and downloads its JSON. `/api/v1/operations/retention` returns the retention preview. Both are owner-only, including for instance-scoped read/submit tokens. The export is at most 1 MiB and has fixed metric labels. It includes:

- Per-ADM retained row counts, request/attempt/source/feed status counts and database/WAL bytes.
- Installation storage against its configured allowance; compare successive reports for growth.
- Serving/background compute duration buckets, outcomes and reserved local-work caps since process start. Reported consumed work is separately counted only when a child returns that measurement; missing measurements are not zero work.
- Current-window provider accounting including unresolved reservations, all retained grant status counts, and separately reported terminal token usage. This is not a provider billing total.
- Local/Lean/component availability, version/generation and retention eligibility.

No source text, queries, model payloads, raw errors, credential values, provider response text, connection names or arbitrary filesystem paths enter the report. ADM identities and activity counts are operational metadata; review before sharing. Process counters reset on restart; persistent store/provider counts survive. These snapshots are local diagnostics, not a monitoring server or a multi-day retention database. Full HTTP-to-result latency is measured by the bounded verification workload, separately from compute duration.

## Retention contract

| Data | Current behavior |
| --- | --- |
| Events | Retained until explicit owner prefix pruning; `event_days` selects an eligible old prefix in the preview. A newer event prevents pruning later rows solely because a wall clock moved backward. |
| Source text, claims and support | Retained with immutable versions and spans, including superseded/disputed material referenced by historical results, models or feeds. |
| Accepted/historical models, policies and proofs | Retained; current and historical binding/evidence checks remain reproducible within the implementation's trust boundary. |
| Private drafts and diagnostics | Retained within episode/store caps; no partial draft can serve. `diagnostic_days` is a review threshold, not a promise of physical deletion. |
| Request/source/feed idempotency and dispatch records | Retained. An old identity cannot become a fresh mutation merely because time passed. Unknown reservations remain charged. |
| Archived ADMs | Preserved and inspectable; archive is not deletion. |

`automatic_cleanup=true` is rejected. `unreferenced_source_days` and `idempotency_days` are review thresholds only. The current implementation chooses preservation over reclaiming space without a complete dependency proof. When caps are reached it refuses/holds new work instead of silently dropping acknowledged input. Owner-requested [model deletion](MODEL_LIFECYCLE.md) removes a named instance through durable fencing and app/gateway cleanup. Paired restore preserves requested, fenced, draining, purging, blocked and completed deletion records; it cannot reactivate those models. Gateway redaction acknowledgements and uncertain usage survive independently. Automatic evidence-graph garbage collection and compaction remain future work.

Owner event pruning uses `POST /api/v1/adms/{adm}/events/prune` with `{"cursor": N}`. Use the displayed eligible prefix and review consumers first. Consumers behind the retained floor receive `410 cursor_expired` with a resynchronization instruction; reload current resources and resume from `earliest_cursor`. Event pruning does not delete request results, evidence, model revisions, source sequences or idempotency keys. Events are notifications, not the sole record of accepted knowledge.

## Verified envelope and release boundary

The [test guide](TESTING.md) describes reproducible finite and runtime checks. [Release scope](RELEASE.md) defines the supported platform and operational limits. Bounded tests do not establish indefinite operation, arbitrary failure recovery or a formal refinement proof.
