# Teaching change reports

Teaching reports what was actually published, using checked declarations and source evidence from the revisions immediately before and after admission. A requested objective or provider explanation is not evidence that a change happened. Reporting does not change admission, dependency handling, proof status or historical retention. Local work accounting includes checked report construction and snapshot export before a successful admission returns.

## Meaning of a change

| Classification | Checked meaning |
| --- | --- |
| `added` | A declaration entered the active model. |
| `definition_changed` | The declaration's canonical definition changed, including its interface, carrier or body. This does not prove that two different definitions are logically inequivalent. |
| `preserved_dependent` | The complete canonical definition stayed identical, but at least one referenced declaration acquired a different artifact identity. The candidate was checked again with those bindings. |
| `evidence_changed` | The definition stayed identical and its support changed, without changed dependency bindings. |
| `rebound` | The definition stayed identical while its artifact identity changed, without the preceding dependency/support distinctions. |
| `removed` | The declaration left the active model. Earlier revisions and evidence remain historical records. |

A preserved dependent rule can produce different answers after its premise changes. The report establishes exact definition preservation and successful admission, not unchanged consequences or reused proof certificates. New consequences require their own supported local queries. Support changes are retained in the before/after support hashes even when the primary classification is a definition or dependency change.

For source facts, the report also retains entity, predicate, typed value, unit, temporal cell, exact source span/version and whether support was held. A point is described as an instant; an interval retains its exclusive end. Renewed support for the same value is distinguished from a changed value. Reports do not assert external truth or establish coverage outside the recorded cell.

## Durable records and interfaces

Accepted acquisition and source-projection receipts carry `effects.change_report`, profile `awm-adm-publication-changes/1`. Existing `added`, `replaced`, `removed`, `declarations`, `support_changed` and `support` fields keep their artifact-level meaning. In particular, `replaced` can include a preserved dependent whose artifact was rebuilt.

Each entry carries the symbol, classification, before/after description and definition digest, canonical definitions up to 2,048 bytes each with an explicit `definition_complete` flag, declaration/support hashes, changed dependency references and any source-fact metadata. The report binds before/after theory roots and admission mode. Receipt fields bind the decision and accepted revisions/contexts. Source publication records these details atomically with the accepted revision; later model changes cannot rewrite that report.

Direct Teach views expose both acquisition and source-projection receipts in `teaching.admissions`, ordered by receiver sequence. `teaching.summary.changes`, profile `awm-adm-teaching-changes/1`, combines accepted publications, retaining their objective, receipt and revision identities. Rejected candidates produce no accepted changes. Several accepted children may have different revisions; this is a sequence of publications, not a synthetic single atomic change. A later failure does not hide earlier published portions.

Reports include at most 32 entries within a 12,000-byte entry budget, with bounded descriptions and dependency lists. `complete`, `dependencies_complete`, `publications_complete` and description `abbreviated` flags distinguish coverage from readable detail. A bounded summary can omit additional entries without discarding the exact retained receipts. Historical receipts may omit the report; consumers must treat that absence as incomplete information. New aggregates containing such receipts set `complete` to false. Stored historical summaries are not rewritten or reconstructed from provider prose or today's model. These are additive receipt/task fields; existing serialized finite/snapshot profiles and storage schema are unchanged.

## Conversation and Codex

The completion provider receives the bounded checked report in the existing narration call; reporting adds no provider call. It explains prior and accepted meanings, preserved dependents and unfinished work. An abbreviated short description can still include the complete bounded definition for narration to explain. When that structure exceeds its bound, it is omitted explicitly rather than interpreted speculatively. Narrative strings remain data and cannot authorize work or change modes.

The console retains a deterministic change note for revisions, even when fluent narration is available. Partial outcomes retain the full saved-and-unresolved summary. The current forward-mode reminder comes from current service state; an old publication's mode is not evidence of today's mode. The Codex plugin receives the same summaries and receipts and follows the same distinction between a changed rule and a rebuilt unchanged dependent. Neither path silently changes the mode or runs extra queries to embellish an explanation.

An illustrative outcome is: “Changed the limit from 2 to 3. The eligibility rule stayed unchanged and was checked against the new limit.” That statement requires matching checked records. Whether a particular input now qualifies is a separate query, not an inference promoted from the explanation.

Tests cover transitive dependent preservation, interface changes, additions/removals, evidence-only and value-changing source publications, historical bindings, bounded/legacy reports, rejected candidates, source-teaching delivery and partial failures. See [testing](TESTING.md) and [automatic teaching](TEACHING_EXECUTION.md).
