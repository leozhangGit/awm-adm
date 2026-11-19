# History and accepted-knowledge search

A model's **History** shows Ask, Teach and structured API activity together. Related local requests, acquisition children and managed source processing are grouped under their parent interaction. Standalone learning, extraction, source admission and feed items remain visible as their own activity. A console/API label describes the entry point, not authorization or stronger assurance.

Choose a time range in the viewer's timezone, or leave it empty for all retained history. The service receives UTC milliseconds; the start is included and the end excluded. Stable pagination captures each underlying collection's upper sequence boundary, so a new message does not duplicate or displace older pages, even when timestamps coincide. Refresh starts a new query. Some older source records have no stored creation time; they are explicitly undated and appear in an unfiltered query. No timestamp is invented for them.

History is read-only. It retrieves saved outcomes and original context bindings without repeating a provider call, local request or publication. Original exact requests, results, task records and source provenance remain available through their existing APIs. Historical results are not presented as a fresh check against today's model.

**Model & evidence** searches the current accepted declarations and evidence by symbol, type, rule text, units or source. It renders readable finite rules and bounded evidence excerpts. Declaration entries retain exact artifact identities and evidence references in the API. Search pagination binds the current revision; if the model changes, a fresh search is required. There is no owner-epoch selector. Historical model/result APIs remain available for diagnostics and programmatic use.

## Endpoints

- `GET /api/v1/adms/{adm}/activity?start=…&end=…&limit=30` returns grouped entries, original bindings, `next_cursor` and the count of undated legacy records. Pass the returned cursor as `after` with the same time filter to continue. The API authenticates the model scope on every page.
- `GET /api/v1/adms/{adm}/knowledge?query=…&kind=declaration&limit=30` returns current matches and `revision_id`. `kind` can select declarations, evidence or a specific declaration/evidence kind. Pass `after` and `revision` to continue the same search.

Neither endpoint changes the accepted model, exposes provider credentials or sends data to a remote model. Evidence records describe support and provenance; they do not establish external truth.
