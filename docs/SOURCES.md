# Supplied sources and temporal evidence

See [knowledge intent](KNOWLEDGE_INTENT.md) for adopted rules, sourced observations, model-relative premises and exploratory or quoted material.

The service provides manual and feed-driven bounded source acquisition. The source service stores original material, extracts reviewable claims, compiles selected claims into finite candidates and submits them to ordinary local admission. No source text or extracted claim grants permissions, modifies owner requirements or becomes accepted knowledge by itself. The [feed guide](FEEDS.md) defines continuous scheduling and explicit owner coverage transitions.

## Typed evidence catalog

The [temporal evidence contract](TEMPORAL_EVIDENCE.md) defines `awm-adm-temporal-catalog/1`, the current material-aware Teach output. One catalog can contain instant, occurrence, validity and period-value scopes. Semantic series include exact units, explicit meaning and optional report attribution. The compiler preserves those distinctions in checked evidence annotations while using ordinary finite constants and admission. Legacy projections remain supported through their own unchanged validators and read-only compatibility views.

## Explicit API workflow and authority

Normal Teach coordinates these stages automatically for selected material. The following describes the retained advanced API workflow.

1. Select an ADM in the source API. Install an owner source policy with permitted source IDs, attribution, evidence groups and explicit external-disclosure flags. `projection: null` permits intake and schema proposals before the owner has chosen finite carriers.
2. Install a finite projection schema when ready. Define a namespace, finite entity IDs, semantic predicates with exact carriers/units, and typed temporal scopes. The legacy projection profile retains its ordered disjoint UTC-cell meaning. Install independent behavioral requirements through the requirements API when the application needs them. The provider cannot install either policy.
3. Supply an immutable text, Markdown, JSON or JSONL item. Identity is `(source_id,item_id,version_id)`; receipt time and an increasing source receipt sequence are assigned locally. UTF-8 bytes, content hash and origin are retained. A changed version explicitly identifies the current version it supersedes.
4. Start local structured extraction or one explicit provider extraction. Local extraction reads a JSON fact object/array, one fact object per JSONL line, or `fact {JSON}` lines in text/Markdown. Ordinary prose stays unprocessed unless an owner chooses provider extraction. An external job requires the current enabled connection and source disclosure permission; it shares finite operating bounds, dispatch fences and unknown-outcome accounting with learning/language.
5. Inspect each original UTF-8 byte span, claim, effective time, unit, assertion kind and hold reason. Select eligible claims and build a manual projection episode. Schema proposals are separate unaccepted data; reading one does not install it.
6. Review the generated declarations. Approval binds the current revision and source policy. Complete candidates enter the same receiver-ordered admission queue as ordinary learning. Earlier unresolved reviews hold later publication. Forward/backward conflict rules and installed independent requirements still apply.
7. Query a fact locally through Ask or the durable structured request API. Request/result history records the exact theory/support/epoch binding, claim, cell and generated symbol. Missing cells, unknown scope and disputed support produce `needs_input`, never an invented default.

## Provider structure and local validation

For external fact extraction (`purpose: claims`), the provider-facing schema describes the complete JSON structure: authored field order, required fields (including nullable fields), closed objects, primitive types, enums, arrays and local references. It omits string pattern/format/length constraints, numeric bounds and array-length bounds. This schema is selected by the extraction task, identically for every provider/model, before the first dispatch. It is not a fallback after a failed call. Projection-schema proposals retain their full existing provider schema.

The app still decodes every complete response through the exact decoder selected by its immutable catalog: the legacy `ExtractionOutput`/`TemporalScope` models or typed temporal `Extraction`/`Scope` models. Identifier/predicate syntax, units, lengths, calendar validity, half-open temporal ordering, exact value kinds and safe integers remain checked locally. The bounded extraction child also enforces configured/hard claim limits, original UTF-8 span boundaries and owner projection resolution. Unknown entities, carrier overflow, partial cells and other unresolved semantics remain explicit holds. A response that violates local validation fails as a whole; no partial claims are salvaged. Eligible claims remain unaccepted until separate projection and ordinary admission.

Transport response bytes, token/call reservations, child work/time limits and retained-item bounds remain unchanged. The provider's broader grammar may admit a malformed value that local validation rejects; it confers no authority. Empty claim arrays remain valid output shape but do not demonstrate successful extraction of an explicitly supplied fact. Shape validation cannot prove source fidelity, so review still checks values, effective times and original passages.

## Legacy owner projection profile

`awm-adm-projection/1` uses fixed, explicit finite time cells. This keeps cell identity stable when disjoint historical facts arrive in backward mode. An interval must fully cover every selected cell; partial-cell overlaps are held as `partial_time_cell`. The owner must choose a sufficiently fine grid. Open-ended assertions can cover existing cells but never extend coverage. A point carrier has explicit discrete instants; an interval is not inferred from a point. Intervals are half-open. UTC day/year boundaries must align to midnight/January 1.

Each `(projection,entity,predicate,cell)` becomes a deterministic qualified zero-argument finite function. Its body contains the checked finite value; its exact evidence subset carries the original source, claim, projection and owner source policy. No shared function must be replaced merely to add another disjoint cell. A conflicting value for the same cell becomes an ordinary declaration conflict. Selecting two claims for the same cell in one batch is held for separate review, even when they agree.

Accepted projections retain checked before/after reports alongside their receipt and publication bindings. Reports distinguish changed values from refreshed support for the same definition and retain typed units, time cells and exact source-version spans. Source Teach exposes these receipts through the same interaction view as learned declarations. See [teaching change reports](CHANGE_REPORTING.md).

Predicate carriers and retained fact-cell identities are immutable. The owner can explicitly extend coverage or select a semantic window through the [coverage transition](FEEDS.md#explicit-coverage-and-windows) API. Out-of-window facts receive support holds; history is retained. Source-permission revisions dispute existing source-derived support. No change silently expands or truncates the model.

Default runtime bounds are 100 items/batch, 256 KiB/item, 2 MiB/batch, 100 extracted claims/item, 128 entities, 256 time cells and 4,096 active fact cells. The closed profile schemas also enforce hard carrier limits. Item/queue/storage limits are checked before committing work. Each extraction/compilation/admission uses a separately bounded, network-free compute child sharing background capacity; serving has separate capacity. An extraction job makes at most one provider call. There is no automatic retry of a dispatched or unknown call. App restart stops interrupted manual work; reviewed but unapproved proposals remain inspectable. Feed-owned safe queued local work follows the durable recovery contract in the feed guide.

```json
{
  "projection": {
    "namespace": "history",
    "entities": ["site"],
    "predicates": [{"symbol":"site.capacity","kind":"integer","unit":"places","minimum":0,"maximum":20}],
    "cells": [
      {"kind":"interval","granularity":"year","effective_from":"2020-01-01T00:00:00Z","effective_to":"2024-01-01T00:00:00Z"},
      {"kind":"interval","granularity":"year","effective_from":"2024-01-01T00:00:00Z","effective_to":"2026-01-01T00:00:00Z"}
    ]
  },
  "sources": [{"source_id":"records","attribution":"Owner supplied registry","evidence_group":"owner","allow_external":false}]
}
```

This is an authored example, not a built-in domain. Source content for its first interval can be:

```json
{"entity_id":"site","predicate":"site.capacity","value":{"kind":"integer","value":10},"unit":"places","temporal_scope":{"kind":"interval","granularity":"year","effective_from":"2020-01-01T00:00:00Z","effective_to":"2024-01-01T00:00:00Z"},"assertion_kind":"assertion"}
```

Boolean and enumerated carriers are also supported. Quotations, hypotheses and negations remain labeled evidence, not positive facts. Unknown entities, units, times or out-of-carrier values are held. A free-text generalization or proposed executable rule is outside this extraction language. A small observation set does not authorize a universal definition.

## Corrections and support assurance

A source correction preserves original bytes, claims, candidates and historical query results. A bounded dependency check finds active projected declarations supported by the superseded item. A new support origin records the dispute, and support plus the new revision publish atomically with intake. The executable theory root can remain unchanged while the support root and policy epoch change. Pending old-epoch requests are fenced. New fact lookups and native finite queries depending on disputed declarations are held. Historical results remain statements about their original pinned model/support.

Revalidation records identify affected symbols. Current support remains disputed until checked replacement evidence is accepted under the applicable publication authority. Historical revalidation notices retain their original state. Resolution records bind replacement evidence; current support determines serving without rewriting historical notices. Corrections do not automatically win backward conflicts. A same-value replacement can refresh support; a different value still follows the selected conflict policy. Snapshot evidence includes the projection/source annotations and dispute notes, so imported models retain the local lookup/hold behavior without importing provider permission or live source jobs.

The service also supports `lookup_fact_period`, which requires unique active interval support throughout the requested UTC period and the same computed value, kind and unit across its cells. Gaps, ambiguous support and disputes remain unknown; changing values require a narrower time. Point evidence does not establish a whole-period fact. Date-only legacy validity questions use this operation after application-owned timezone resolution. Typed temporal catalogs use explicit query intent to distinguish validity, occurrences and whole-period values. Exact-instant lookup and existing source artifact encodings remain unchanged. See [temporal interpretation](TEMPORAL_INTERPRETATION.md).

An accepted fact result is **conditional on declared sources**. Hashes prove identity, source spans preserve attribution, and finite checking proves model-relative execution. Neither proves that the external source is true or that provider extraction understood it. Evidence groups and statement digests reveal copies; repeated assertions never acquire independent corroboration weight. Acceptance requires explicit owner authority: per-candidate review, a checked direct Teach task, or a standing checked-auto feed policy with typed fact requirements. Neither establishes external truth. The source-aware service adapter and Python interpreter are trusted code, not formally verified programs.

## Provider failure diagnostics

Failed extraction jobs retain their specific dispatch error. Source history and job detail expose a safe `provider_failure` view, including for older jobs labeled `provider_unavailable`. API diagnostics distinguish incomplete output, provider quota/rate limits, authentication and uncertain transport. Teach presents a readable task outcome; the source and dispatch records retain the exact reason. No failed or partial output becomes a claim. A zero/zero remote token report remains unverified usage with its reservation retained, rather than a free call. The [learning contract](LEARNING.md) defines diagnostics and accounting; inspecting a failure never retries it.

Responses can also retain optional token breakdowns, returned reasoning settings and output-item/visible-text byte counts in the API records. Missing historical values remain unknown; counts neither expose hidden reasoning nor make partial output acceptable.

An advanced API client can deliberately request another extraction through `POST /sources/jobs` with a fresh `reprocess_id`. This creates a new attempt without changing immutable source bytes or bypassing current policy, connection or call limits. The old job and unsettled usage remain. To recover a lost submission response, reuse the same source/pipeline/reprocessing identity and settings; it returns the existing job. Omitting `reprocess_id` returns the original pipeline job. A new attempt requires explicit owner action; uncertain dispatches are never automatically repeated.

## API

All routes are under `/api/v1/adms/{adm}`. Resource identities are instance-scoped; all public operations use the shared local workspace boundary.

| Route | Use |
| --- | --- |
| `GET /sources` | Bounded source/claim/job/episode/support history (`page`, `limit`); complete originals through `/sources/history/{kind}/{id}` |
| `PUT /sources/policy` | Install owner projection/source permissions with expected revision/generation |
| `POST /sources/batches` | Idempotent bounded append or explicit correction; immutable bytes and stable IDs |
| `POST /sources/jobs` | Explicit local/provider extraction or schema proposal, deduplicated by source version and pipeline |
| `POST /sources/jobs/{id}/cancel` | Fence an unfinished extraction |
| `POST /sources/episodes` | Compile selected eligible claims into a complete candidate |
| `POST /sources/episodes/{id}/review` | Approve against current revision or reject |
| `POST /sources/episodes/{id}/cancel` | Cancel without publishing |
| `POST /requests` | Submit `query_evidence` with explicit temporal intent, `recall_evidence` with exact entity/predicate selectors and no time filter, or compatible `lookup_fact`/`lookup_fact_period` requests; each request has a durable idempotency key |

The language Ask/Teach grammar remains available for finite commands. Temporal lookup and [evidence recall](EVIDENCE_RECALL.md) are available through Ask and the structured request API. Ask's entity and predicate choices derive from the owner projection or checked accepted snapshot metadata. Time-filtered queries preserve their explicit temporal conditions; recall returns records across their saved scopes. Both execute locally with no provider fallback. The exact request and declared cells remain inspectable through the API.

The exported schemas in `contracts/schemas/` define request shapes. Source-policy generation, source-head identity, revision, cancellation and publication checks run again after expensive child work. The current owned schema 18 retains source history and supports transactional migration of supported owned stores, preserving finite certificate encodings and historical evidence.

The [release scope](RELEASE.md) describes supported intake and operational limits. Managed push queues process supplied material within configured bounds; they do not pull from external services. Normal Teach uses the enabled connection and the local request's selected material, without a separate spending setup. Engineering live trials require explicit disclosure, scope and test budgets. Application-specific fidelity must be validated for the intended domain.

## Clarification packets

A continued one-shot Teach request can supply an immutable `awm-adm-selected-material/1` packet as ordinary text. Its header records exact original identities/digests and byte ranges relative to the payload; extraction spans index the entire packet. This preserves cross-message meaning without changing the claim schema or source validators. The original entries remain stored separately. Source supersession also holds active facts whose packet contains that original identity, including packet evidence imported in snapshots. Extraction, projection and final publication also reject an older packet when a retained original has a known newer version; reprocessing cannot reactivate that superseded support. The packet grants no extra trust or authority and does not fetch cited URLs.
