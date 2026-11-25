# Changelog

## 0.4.0

Local project integration, temporal evidence and clearer model interaction.

- Login-free console and public API on loopback port 9527, with private internal service authentication retained. Supported upgrades preserve existing models and history in owned schema 18.
- Bundled Codex plugin for project model creation/reuse, natural-language Ask/Teach, durable work recovery, accepted-knowledge recall and explicit forward/backward changes.
- Atomic preservation and rechecking of dependent definitions during conversational corrections, revision-compatible language metadata and accurate partial-completion reporting.
- Checked before/after teaching reports distinguish changed definitions, preserved dependents, evidence updates and active removals.
- Ask/Teach initially load the latest 100 exchanges; Load more adds older batches with stable scrolling. Full history and bounded interpretation context remain independent.
- Typed temporal evidence and scoped recall preserve subject time, report/inspection time, units and attribution. Saved calculations remain distinguishable from new model computations.
- Model-neutral preparation guidance states field bounds and keeps concise objectives linked to complete original teaching inputs. Safe diagnostics distinguish missing information, unsupported capabilities, invalid generated fields, input-capacity stops and provider failures.
- Bounded acquisition supports a 128,000 default input reservation and an independent three-minute call deadline, with retained uncertainty and no automatic retry of dispatched timeouts.
- Overview shows recent model operations in pages of ten; the model collection is listed in Domain models.
- Removed retired login/session implementation and styling; updated product documentation and dependency provenance for the service, console and plugin.
- Fixed plugin installation isolation, invalid-port handling and source-admission work accounting.

The public API remains `/api/v1`. Finite model, snapshot and result format identifiers are unchanged.

## 0.3.0

First public release of the standalone AWM-ADM service.

- Local finite models, independent owner requirements, ordered admission, planning and invariant certificates.
- Administrator setup, password login and local recovery.
- Direct Ask/Teach streams, automatically managed context, checked teaching, bounded background learning and readable outcomes with retained evidence.
- One tested Enable/Disable provider connection, observed token/call charts and no automatic uncertain retries; no financial setup is required.
- Attachments, dated source facts, corrections and bounded managed push intake.
- Independent snapshot export/import, naming, conflict modes, archive and durable deletion.
- Docker runtime, unified authenticated `/api/v1` API, paired backup/restore and operational diagnostics.
- System-timezone interpretation, evidence-backed historical lookup, unified history/search, retained drafts and chat scrolling with natural page handoff.
- Publication exclusions and credential checks for source exports, with synthetic regression fixtures kept separate from private operational material.

See [release scope](docs/RELEASE.md) for supported boundaries. API and serialized-profile version identifiers retain their compatibility meaning within this release.
