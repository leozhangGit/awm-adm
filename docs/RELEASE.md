# AWM-ADM 0.3.0

0.3.0 is the first public standalone release. It provides locally maintained finite ADMs, checked learning, conversational Ask/Teach, supplied-material intake and independent model management through a loopback API and console.

## Supported envelope

- One administrator, multiple independent models, one local host.
- Linux ARM64 Docker containers; Python 3.13, Node 22 and Lean 4.19.0 are pinned in the build.
- Owned SQLite schema 15 with transactional compatibility and paired-restore checks.
- Fixed provider transports and explicitly configured supported pricing; recorded adapters for automatic tests.
- The public API uses `/api/v1`, with separate `interpretation-sessions` for manual previews and `conversations` for Ask/Teach. Artifact/profile versions remain unchanged for compatibility.

## Product capabilities

Password setup/login/recovery; durable Ask/Teach; checked read-only interpretation and local execution; bounded preparation/acquisition/diagnostic revision; semantic/source review; priced interaction/learning lanes; immutable attachments and dated facts; managed push intake; snapshots, naming, conflict modes, archive/deletion; diagnostics and paired backup/restore.

Advanced model tools exposes manual Learning and Sources workflows. Local debug executes structured requests without remote inference. Unknown evidence remains unknown. Time-only renewal of an unchanged unstarted preparation cannot increase its resource caps, repeat provider preparation or start execution automatically.

## Assurance and limits

[Testing](TESTING.md) describes meaningful coverage and reproduction. Automated provider checks use recorded/simulated responses. A bounded equipment walkthrough exercised accepted borrowing/history knowledge and supported/unknown Ask outcomes; it does not measure arbitrary-domain or general language reliability. Original observed failures motivated regression tests and are not recast as successful live runs.

Local validity and owner conformance do not establish external truth. Lean kernel proofs and exhaustive executable correspondence are distinct; Python interpretation and translation remain trusted. A budget limits work rather than guaranteeing successful learning. Unknown provider usage remains reserved, and costs are estimates rather than provider invoices.

Federation, cluster reasoning/Byzantine coordination, public hosting, multiple administrators, arbitrary sustained workloads, general theorem declarations, physical actions, crawling/pull connectors and arbitrary PDFs/OCR are outside this release. Broader accessibility and security certification are not claimed.

## Installation and distribution

Follow [Installation](INSTALLATION.md). New stores start with no administrator, model, provider connection or spending authority. Existing supported installations retain their stores during ordinary restarts/updates; do not delete volumes for an update.

Source exports contain standalone code, tests, fixtures and product documentation, with a SHA-256 inventory and no runtime credentials/history. See [Contributing](../CONTRIBUTING.md), [MIT license](../LICENSE) and [third-party notices](../THIRD_PARTY_NOTICES.md).
