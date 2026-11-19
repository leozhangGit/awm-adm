# Continuous source-driven learning

A feed is an owner-installed standing policy for one ADM. Once explicitly enabled, it consumes newly received versions from selected source identities without a foreground request or another manual start. It drives the same bounded extraction, finite projection and ordered admission used by manual source work. Local serving retains separate compute capacity. Source material is data, never authority.

## Entry points

Normal supplied-material learning uses Teach. Integrations needing a managed push queue use the source-queue API described in [Intake](INTAKE.md). The task establishes a checked finite source scope and coordinates extraction, projection and admission automatically.

The explicit source/feed APIs remain available for advanced integrations: install a source policy/projection, create a feed with selected sources/cursor and finite processing limits, then enable it. External extraction uses the current enabled connection and declared disclosure. `review` retains an explicit candidate hold; `checked_auto` requires the feed's typed predicate requirements, independently of provider assertions. ADM behavioral requirements apply to either mode. Feed creation itself is not empirical validation of its sources.

Append immutable source versions with stable batch/item/version identities. Receipt means stored, not learned. Inspect API counters and held reasons; pause preserves cursors/reservations. A deliberately requested reprocessing pass has a new identity. No pull connector is implicit.

The feed specification is immutable. Create a new explicit policy to change sources, extraction configuration, requirements, coverage generation or lifetime processing limits. A mode/owner-policy epoch change stalls existing authority; an explicit resume acknowledges the current epoch. A changed source-policy generation requires a new feed specification. Pausing remains possible after such a change.

## Finite scheduling and accounting

| Boundary | Implemented behavior |
| --- | --- |
| Micro-batch | One source version per scheduling step; at most 32 unrelated receipts scanned per step. One extraction call per external job. Claims are all-or-held: no silently selected subset from partially resolved extraction. |
| Fairness | Round-robin feed scheduling across ready ADMs, round-robin source execution across ADMs, bounded pending work per feed (default 4, maximum 32). Waiting provider outcomes do not prevent runnable local jobs from progressing. |
| Serving | Separate serving and background process slots. Extraction, projection and admission share bounded network-free background children with other learning work. |
| Processing limits | Lifetime item/call/input-token/output-token/local-work reservations, charged before scheduling. Each item reserves three configured request work limits. No refunds for unused, shared, failed or uncertain feed reservations. |
| Provider dispatch | Actual dispatches also pass per-call bounds, configured concurrency and exact gateway authorization. A shared call is charged once globally; each interested feed conservatively reserves a full item. |
| Period boundary | Feed reservations never expire. Calendar changes cannot clear uncertain usage; no rolling financial quota gates new work. |
| Retention/backpressure | Existing per-ADM item/byte and installation storage caps include feed policies, interests, runs and transitions. Maximum 100 retained feed specifications per ADM. Full pending allowance holds the source cursor; storage/intake caps reject before acknowledgment. No automatic deletion or eviction. |
| Stopping | Default three consecutive unsuccessful item completions disable the interested feed. Held items, invalid data, rejected conflicts and interrupted work remain inspectable. Accepted work resets that feed's consecutive failure count. |
| Retry | Only orchestration failures before an operation is created (`busy` or `quota_exceeded`) receive bounded exponential backoff, default two retries from two seconds. Completed or uncertain source jobs are never automatically repeated. |

Reservations are intentionally conservative work authorization, not billing estimates or promises that a gap will close. Unknown usage is reported separately from measured tokens. Feed processing limits and per-call bounds are separate; enabling a policy does not enlarge either or choose a different model.

A review hold can block later candidate **publication** in the ADM's shared receipt order. It does not prevent extraction or serving from the accepted revision. Candidate arrival order is distinct from source receipt sequence and effective event time. Forward/backward conflicts retain their normal meaning.

## Shared interests, cancellation and recovery

Source-version/policy/extractor/connection/call-limit identity deduplicates processing. Multiple feed interests can refer to one run. Pausing one feed does not revoke another valid interest. An ordinary manual extraction remains owner-authorized independently of feed pause. Demand-driven learning retains its existing request-interest cancellation rules; different acquisition contracts are not conflated merely because their text resembles a source item.

Every feed-owned compute/dispatch/publication step checks remaining enabled, current interests. Automatic approval additionally binds the approving feed generation; pausing it cannot leave an approval usable under an unrelated review-only feed. With no valid interests, publication is fenced. A shared job's explicit owner cancellation cancels that job for all of its interests; it is different from pausing one feed.

Feed cursors, reservations and run identities are durable SQLite data. Safe queued local work can resume after restart. Interrupted compute and any job with a reserved/dispatched external call require explicit reprocessing. Registry reservation intents are checked even if the process stopped before copying the grant ID into the source job. Unknown outcomes remain charged and are never blindly dispatched again. Existing review candidates retain their receipt order; restarted approvals return to review eligibility.

Completed feed-owned jobs and episodes retain their original generation, deadline, payload and decision records across recovery. Only eligible unfinished work receives refreshed operational bindings. Recovery neither requeues completed work nor refunds its reservations.

A deliberate `reprocess` command creates a new recorded pass and consumes a new reservation. It does not edit the previous attempt, refund it, change its source bytes or bypass current policy. An unchanged idempotency key replays the same command result.

## Explicit coverage and windows

`POST /sources/coverage` is an owner-only compare-and-swap against the current revision and source-policy generation. The transition is checked in a bounded child, then publishes its policy, support revision and history atomically.

- `extend` retains all existing cells and may add bounded entities, predicates or disjoint cells.
- `window` selects another explicit bounded set of cells. Facts outside it receive support holds. Original declarations, evidence and historical query results remain retained; this is a semantic window, not storage cleanup.
- Existing namespace, entity membership, predicate carriers and time interpretation cannot be redefined. A retained fact cell cannot be split, merged or partially overlapped by a new cell. Unsupported changes fail without publishing.
- The compiler reuses the original symbol/projection identity for an existing cell, so extending coverage does not manufacture a new conflict slot. Newly added cells receive ordinary deterministic identities.
- Re-entering a previously held window requires fresh checked evidence; a coverage change alone does not restore disputed support. Facts outside coverage stay unknown/held, never false or zero.

Current result bindings carry the source-policy generation along with the theory/support/epoch. Historical results retain their original binding. Source evidence annotations preserve window holds in portable snapshots. An imported ADM still needs its own receiver-owned source/feed policies before learning.

Windows do not free fact/storage capacity. Carrier changes, retention and operational backup follow the bounds in [Operations](OPERATIONS.md).

## API

All paths below are relative to `/api/v1/adms/{adm}`. Reads require instance read authority; mutations require the owner. Schemas are exported under `contracts/schemas` and the authenticated OpenAPI endpoint.

| Method and path | Input/result |
| --- | --- |
| `POST /feeds` | `Feed` with idempotency, revision/source generation, immutable policy and finite processing limits. Returns the durable feed. |
| `GET /feeds?after=0&limit=20` | Feed summaries plus processing-interest history with increasing cursor (limit 1–100). |
| `PUT /feeds/{id}` | `FeedControl`: expected generation, current revision, enabled flag. |
| `POST /feeds/{id}/reprocess` | `FeedReprocess`: idempotency, expected feed generation and source receipt sequence. |
| `POST /sources/coverage` | `CoverageTransition`: expected revision/generation, kind, complete projection and owner reason. |
| `GET /sources?page=0&limit=20` | Bounded reverse-order UI history for each source collection, limit 1–50. Offset pages are a browsing view and may shift during appends; they are not durable consumption cursors. |
| `GET /sources/history/{kind}/{id}` | Complete retained version/job/claim/episode (`versions`, `jobs`, `claims`, `episodes`). Overview excerpts are labeled and never replace the original evidence. |

The append API remains `POST /sources/batches`. Feed IDs target one ADM through the route; source content cannot choose a different target, provider, budget or publication policy.

## Verification scope

Recorded-provider tests exercise intake, cursors, bounded scheduling, shared interests, pause/resume, correction holds and ordinary ordered admission. See [Testing](TESTING.md) for reproducible checks and limits. These tests do not establish the accuracy of arbitrary source material or indefinite ingestion capacity.
