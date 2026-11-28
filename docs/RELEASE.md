# AWM-ADM 0.4.0

0.4.0 provides a login-free local workspace and a bundled Codex project plugin, with checked revision reports and paged conversation history. It includes locally maintained finite ADMs, checked learning and reaffirmation, conversational Ask/Teach, supplied-material intake, shared provider limits and independent model management through a loopback console/API, with optional trusted native container access through an explicit private-network policy.

## Supported envelope

- One trusted local workspace, multiple independent models, one local host; no user login.
- Linux ARM64 Docker containers; Python 3.13, Node 22 and Lean 4.19.0 are pinned in the build.
- Owned SQLite schema 19 with transactional compatibility and paired-restore checks.
- One test-and-enable connection using fixed provider transports; recorded adapters for automatic tests.
- The public API uses `/api/v1`, with separate `interpretation-sessions` for manual previews and `conversations` for Ask/Teach. Existing core encodings retain their meaning; new temporal evidence has distinct profiles and a required-feature snapshot envelope.

## Product capabilities

Direct login-free workspace access; durable Ask/Teach; checked read-only interpretation and local execution; bounded preparation/acquisition/diagnostic revision; automatic checked admission with semantic clarification; immutable attachments and dated facts; managed push intake; snapshots, naming, conflict modes, archive/deletion; diagnostics and paired backup/restore; a bundled Codex project plugin using the same Ask/Teach workflows.

The console provides Ask, Teach, Model & evidence, History and Settings. Advanced structured reasoning, proof, requirements, learning and source/feed APIs remain available. Unknown evidence remains unknown; a financial setup or idle clarification expiry is not required.

Installation-wide [Settings](SETTINGS.md) persist the shared provider input/output/timeout policy and accumulated temporal predicate cap. Newly created work captures these values; active work and identical replays retain their original bounds. Temporal catalogs permit up to 65,536 predicate identities, with separate working-set, entity, scope, fact, storage and compute limits. This is a structural ceiling, not a verified large-codebase throughput claim.

[Reaffirmation](REAFFIRMATION.md) records a caller's endorsement of exact accepted definitions through ordinary checked admission, without acquisition for that objective. Definitions remain unchanged while evidence support and the publication revision can advance. Portable [teaching intent](KNOWLEDGE_INTENT.md) distinguishes the original caller's asserted basis from provider-generated content; it does not certify human agreement or external truth.

## Assurance and limits

[Testing](TESTING.md) describes meaningful coverage and reproduction. Automated provider checks use recorded/simulated responses. A bounded equipment walkthrough exercised accepted borrowing/history knowledge and supported/unknown Ask outcomes; it does not measure arbitrary-domain or general language reliability. Original observed failures motivated regression tests and are not recast as successful live runs.

A separate bounded native Codex walkthrough exercised project binding, teaching and asking, backward preservation, explicit forward revision, dependent-definition rechecking, return to backward, fresh-chat recall and no-project handling. An initial revision failure led to general service corrections before the successful preservation check. These observations establish the tested workflow, not continuous monitoring, enforcement or universal formalization reliability.

Local validity and owner conformance do not establish external truth. Lean kernel proofs and exhaustive executable correspondence are distinct; Python interpretation and translation remain trusted. Finite work limits do not guarantee successful learning. Unknown provider usage remains unresolved rather than counted as free.

Federation, cluster reasoning/Byzantine coordination, public hosting, multiple administrators, arbitrary sustained workloads, general theorem declarations, physical actions, crawling/pull connectors and arbitrary PDFs/OCR are outside this release. Broader accessibility and security certification are not claimed.

## Installation and distribution

Follow [Installation](INSTALLATION.md). New stores start with no model or enabled provider connection. Existing supported installations retain their stores during ordinary restarts/updates; do not delete volumes for an update.

Source exports contain standalone code, tests, fixtures and product documentation, with a SHA-256 inventory and no runtime credentials/history. See [Contributing](../CONTRIBUTING.md), [MIT license](../LICENSE) and [third-party notices](../THIRD_PARTY_NOTICES.md).

## Temporal evidence

Mixed temporal evidence supports exact instants, uncertain occurrences, validity intervals, whole-period values and attributed reports in one ADM. Local scalar/collection queries retain exact units, source support and temporal intent. Partial accepted-interval resegmentation, implicit temporal aggregation and universal semantic alias resolution are not supported. See [temporal evidence](TEMPORAL_EVIDENCE.md).
