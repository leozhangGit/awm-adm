# Attachments and managed source intake

Teach connects to immutable Sources and the bounded feed scheduler. Owners can attach Markdown, UTF-8 text, JSON or JSONL, or paste supplied material. Providers propose finite mappings and claims; the ADM checks and publishes locally. This is a bounded source workflow, not a pull-connector platform or guarantee of external truth. Current owned schema is 15.

## User workflow

1. Open Teach and establish an exact dollar allowance. Choose ongoing source intake only when a producer should continue supplying material. Ask has a separate allowance.
2. Describe the desired knowledge and attach or select retained material. Upload stores original bytes locally; it neither sends them to a provider nor teaches the model. The message's explicit file-disclosure checkbox permits those selected originals in funded preparation. Unselected files and other conversations are excluded.
3. Preparation asks about unclear entities, units, dates, finite bounds or rule-versus-observation intent. It proposes a checked specification with selected input identities. Provider-proposed behavioral requirements remain uninstalled.
4. Review the readable scope. Start teaching separately authorizes the exact finite source permissions/coverage and material disclosure. The coordinator installs that source policy, stores source records, then reserves extraction, projection and admission through existing services. Capabilities and facts can be separate children of the same ordinary task; their dependencies and parent allowance remain binding.
5. Review extracted assertions and their dated passages in Teach. Acceptance goes through normal ordered admission and the selected conflict mode. Completion reports accepted work and unresolved scope separately. Full candidates, identities and accounting remain in Details/Local debug.

The original attachment survives a page reload and can be selected using **Choose retained material**. Removing it from the composer only removes that message reference. Re-uploading the same exact original returns its retained identity. A same-named changed file proposes an explicit correction of the current source version; uploading alone does not activate the correction.

A complete source mapping must match selected attachment identities. Existing finite coverage cannot expand implicitly. A task needing different coverage stops for a separate owner decision. A source-only task without attachments can use its selected pasted owner turns as immutable source text. An empty standing queue can start with explicit finite coverage and wait for a producer. Extraction holds the whole item when any assertion lacks the required evidence or coverage; it does not silently accept a convenient subset. Natural-language clarification and source extraction remain fallible provider behavior.

## Standing queues and producer boundary

A standing queue is one material child under one explicitly funded source allowance. It lasts at most 24 hours, bounded further by the approved price validity, and never refills automatically. Preparation, extraction, local checks and completion use the same learning-lane allowance. Capabilities use ordinary tasks rather than an open-ended mixed queue.

The parent owns its feed. Pause/resume/cancel and candidate review happen through Teach; AWM-ADM feed controls, reprocessing and source-review endpoints cannot bypass this authority. Pause preserves received items and reservations while stopping new dispatch/publication. A known provider response arriving during pause can be retained, but cannot publish until valid resumed authority. Cancel preserves previously accepted knowledge and unresolved accounting.

**Finish receiving material** freezes the current source sequence, rejects new pushes and drains the already received scope within the remaining limits. A cap, deadline, failed item or no-progress stop produces a partial/unresolved outcome; received originals remain stored. There is no promise that all acknowledged material will be learned. Reprocessing is an explicit newly funded Teach task selecting retained material, with a new feed/job identity; an uncertain dispatched call is never repeated automatically.

The owner can issue a short-lived append credential from an active standing task. Its scope binds exactly one ADM, task/specification and permitted source set. It cannot read the model, submit queries, change provider settings, issue grants, approve candidates or publish. Its receipt endpoint exposes only that credential's acknowledgements. Credentials can be revoked through the existing owner token endpoint. Issuance returns the secret once; do not put it in source files, URLs, screenshots or logs. Lost credential-issuance responses require revocation/reissuance rather than recovery of stored plaintext.

A connector supplies `AppendInput`: a durable `idempotency_key` and up to four source records. Each record binds source/item/version, UTF-8 content, media type, attribution and an optional exact current `supersedes_version`. Provider/model/budget/policy fields are forbidden. `202` means durable receipt, **not acceptance into the theory**. The receipt and source changes commit together; a lost HTTP acknowledgement can be recovered by retrying the identical body with the identical credential/key. Reusing a key with different data fails. Receipt reads and exact acknowledgement replay remain available while paused; new pushes do not.

[`scripts/push_source.py`](../scripts/push_source.py) is the small producer example. With an issued append credential in `AWM_ADM_APPEND_TOKEN`, use `--endpoint` with the exact queue push URL and `--batch` with a retained JSON `AppendInput` file. `--receipt` takes the original batch idempotency key and reads its acknowledgement instead. It refuses remote plaintext HTTP and redirects, makes no automatic retry and never creates authority. An unknown acknowledgement requires the same batch identity, not a new one. No Slack, OAuth, pull polling, crawling, OCR, PDF parsing or new stream engine is included.

| Response | Producer behavior |
| --- | --- |
| `202` | Retain the receipt; track processing through the owner workspace. |
| `429 rate_limited` / `intake_full` | Back off; retry the identical batch after the rate window or backlog permits it. No acknowledgement was committed. |
| `409` stale/conflicting scope | Stop and ask the owner to reconcile scope/version/task state. Do not change the submitted meaning under its old key. |
| `403` / `401` | No usable authority; stop. |
| `422` | Correct invalid input under a new submission identity. |
| Transport timeout / lost response | Outcome unknown; replay the identical request while the credential is valid. |

## Bounds and accounting

These are implemented candidate defaults, not guaranteed throughput or promises to close knowledge gaps. Smaller configured installation/source limits also apply.

| Dimension | Bound |
| --- | --- |
| File types | UTF-8 `.md`, `.txt`, `.json`, `.jsonl`; no NUL, path-bearing filenames or binary files |
| Attachment | 256 KiB original UTF-8 bytes; four selected per message |
| Retained uploads per ADM | 100 originals, 8 MiB encoded records, 1,000 submission identities |
| Push | Four items; each at most 256 KiB; existing HTTP/batch limits still apply |
| Backlog across active managed queues on one ADM | 100 unique pending originals / 8 MiB encoded records; paused queues count |
| Acceptance rate | 60 items per minute per credential **and** ADM |
| Feed | Four pending processing items; standing feed lifetime at most 20 items; one-item scheduling turns |
| Parent | Six calls / 192,000 input / 49,152 output tokens / 12 million local work units / 16 child reservations |
| Provider step | Verified input bound (default 32,000), 8,192 output tokens, 60 seconds, within all remaining caps |
| Local phase | At most 1 million work units / 5 seconds; each feed item reserves three phases |
| Source policy / correction hold | Separate idempotent local-check reservation before bounded computation |
| Completion | One call / 4,096 output tokens protected inside the parent allowance |
| Ordinary task / standing task | 15 minutes / up to 24 hours; no automatic extension |
| Semantic review | At most 24 hours; an approved retained candidate may finish locally after the active deadline without starting a new provider call |
| Append credential | Default one hour, at most 24 hours and never beyond the active task deadline |

A 256 KiB file may exceed a provider's smaller funded input bound: retention does not guarantee dispatch. Conservative work reservations can stop processing before the theoretical feed item limit. Unknown/failed dispatch reservations are retained; accepted facts are not rolled back when the remainder of an allowance expires. Completion can list the same source objective as partially accepted and unresolved, with an explicit accepted-item count.

Intake retains bounded originals before acknowledging them. Extraction/projection/admission reserve processing separately before work. The scheduler rotates across models and feeds; it does not hold an unbounded producer loop. Ask's protected money/token/call/serving capacity remains separate. These are bounded scheduling controls, not a hard real-time latency guarantee.

## Correction, context and evidence

Source receipt sequence, event time and candidate arrival sequence remain distinct. A correction identifies the current source version; storing it atomically holds dependent accepted support. Fresh local lookups then report `needs_input` until valid replacement support is admitted. Previously saved results retain their original revision and evidence.

Forward mode permits a later conflicting replacement; backward mode still preserves the earlier theory and rejects it. Supersession alone cannot bypass precedence. Both modes enforce local validation and independently installed requirements. A mode change applies to future decisions and fences existing task authority.

Source policy installation and source-support/admission commits owned by the task advance that parent's binding atomically. Only its own feeds receive the corresponding epoch update. Other owner, mode, source, vocabulary, provider or spending changes fence the task rather than being silently adopted. Additive managed source permissions preserve unchanged existing provenance; direct AWM-ADM source-policy edits retain their full-hold behavior.

Historical support notices are immutable. The current view derives unresolved/partially resolved/resolved from active support. New resolution records bind the observed accepted revision, theory/support roots and replacement claims; an old notice is not rewritten to say it was always resolved. Existing pre-source notices can show current resolution without a fabricated historical resolution record. Feed stall views derive current state and clear stale reasons after progress.

## Storage, API and recovery

Schema 14 adds `intake_material`, `intake_upload_keys`, `intake_receipts` and `source_notice_resolutions` to each instance; registry migration updates its installation journal. Existing immutable task/turn/source/charge stores are reused. Schema-13 data and previous migration histories remain intact. Paired service restore revokes credentials and remote/spending authority and pauses feeds; restoring content is not permission to resume a producer.

The owner routes are `GET/POST /api/v1/adms/{adm}/attachments` and `POST /api/v1/adms/{adm}/intake/{task}/credentials`. Append routes are `POST .../intake/{task}/push` and `GET .../intake/{task}/receipts/{original_submission_key}`. Task commands add exact `source_consent` at start and `finish` for an ongoing source task. Message input has optional `disclose_attachments`; setup has optional `source_queue`. False/omitted extension fields retain historical idempotency fingerprints. The archived specification oracle remains unchanged; [OpenAPI](../contracts/openapi.json) is the current runtime contract.

Recovery preserves originals, feed cursors, lifetime reservations, known candidates and accepted publication. Unknown dispatch is never blindly retried. Parent/source generation checks are re-evaluated before dispatch and publication; no source or conversation worker is started before the runtime exposes both services. The interpreter, scheduler and transaction implementation remain trusted code.
