# Queryable knowledge and evidence recall

Teach represents the subject people want to consult. Its typed value or event scope is separate from the source, the time someone inspected it and the time a report was published. A source-backed subject fact need not become a Boolean statement that someone read a sentence. Conversely, an observation about reading a source remains that observation; its descriptive prose is not automatically a new typed subject fact.

Preparation guidance identifies the intended questions and their supported read or computation path. Source extraction follows the checked catalog without changing its meaning. A saved calculation retains its attribution, inputs and recorded context. A reusable calculation requires an executable capability; storing an earlier result does not establish a new ADM derivation. The ready-plan and source validators remain authoritative. Guidance helps propose useful representations but cannot prove that natural-language meaning has been captured correctly.

## Local recall contract

Use the existing request API for bounded retrieval without a time filter:

```json
{
  "idempotency_key": "recall-capacity-records",
  "query": {
    "op": "recall_evidence",
    "selectors": [{"entity_id": "room", "predicate": "room.capacity"}],
    "limit": 100,
    "cursor": null
  }
}
```

The [RecallQuery schema](../contracts/schemas/RecallQuery.schema.json) permits 1–32 distinct exact entity/predicate pairs and 1–100 returned records per page. There are no wildcards, implicit latest selection, invented temporal bounds or aggregation. Normal request work/time/storage limits also apply. Ask validates its selectors against disclosed catalog names before submitting the request; catalog coverage alone never establishes a value.

The service cold-checks immutable source bindings and executable constants, selects matching accepted evidence across its recorded scopes, and evaluates the corresponding finite definitions locally. It returns a collection with:

- Typed `value`, exact `unit`, `entity_id`, `predicate` and subject `scope`.
- The retained `meaning`, `qualifiers`, `metric` and direct/reported attribution.
- Separate `observed_time`, `reported_time` and optional `occurrence_id`.
- Exact source version/digest/byte-span reference, claim identity and declaration symbol. Source bytes are not disclosed to Ask interpretation or narration.

The result uses the existing result/binding profiles. Its assurance claim is `accepted_collection`, with source truth conditional on the declared evidence. It contains no scalar consensus or new arithmetic claim. Empty records do not prove absence in the world. Different sources, reports, precision and values remain separate records. Disputed or correction-held matching support returns `needs_input`, preserving snapshot holds as well.

## Paging, completeness and context

Rows have deterministic scope/symbol order. A cursor binds the query, selection, page size, theory, support and request context; it cannot be reused with another selection or changed context. `scope.complete` is true only when the first page contains the entire result. `enumeration_complete` marks the final page. `next_cursor` allows a structured client to continue. `unmatched_selectors` identifies requested pairs with no accepted rows; it is not a world-state negative.

A page can be valid without being complete. The service does not infer uniqueness, agreement or a latest value from an incomplete page. A compute limit remains inconclusive. Recall does not trigger learning, update a model, change conflict mode or make a provider call when submitted as a structured local request.

## Ask and presentation

The model-neutral interpreter can emit `recall evidence with {…}` for questions about relevant saved evidence with no requested time filter. It can include several relevant source-qualified series without requiring an arbitrary source choice. Questions with explicit temporal conditions still use the appropriate [temporal query](TEMPORAL_EVIDENCE.md); recall must not silently discard those conditions. Genuine ambiguity about subject, property or intended meaning remains a clarification.

The returned subject scope can answer when a represented event occurred. Its observation time cannot substitute for that scope. An earlier calculation is described as a saved result, not a computation newly performed by ADM. Meaning/qualifier strings contextualize the typed fields; a date or number found only in descriptive prose is not a newly checked typed answer. Source observations that lack the desired typed subject representation retain that limitation.

Deterministic output and the bounded narration packet preserve the same values, units, scopes and provenance. Narration must retain disagreement, missing selectors and partial-page limits. The packet has a 32 KiB ceiling; oversized packets skip narration and keep the bounded local outcome. Existing accepted facts, historical results and snapshots are never rewritten to make them easier to query.

## Verification boundary

Offline regressions cover full recorded Teach→Ask flows, distinct event/inspection/report times, supplied-calculation recall, unrelated measurements/inventory/forecasts, multiple records, pagination, context fences, empty results, correction holds and legacy/snapshot reads. They check successful storage separately from actual local recall and new computation. Simulated provider replies establish service integration behavior, not general live-provider interpretation reliability. The algebraic kernel, source/claim admission and temporal identity validation remain unchanged.
