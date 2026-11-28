# Service settings

**Settings**, immediately below **Operations**, controls four installation-wide operating limits. The console displays timeout in seconds. The API and configuration file use milliseconds.

| Setting | Default | Supported range |
| --- | ---: | ---: |
| Input reservation ceiling per call | 256,000 | 1–1,050,000 conservative input units |
| Output token ceiling per call | 32,768 | 1–100,000 tokens |
| Provider execution timeout | 360 seconds (6 minutes) | 0.001–600 seconds |
| Accumulated temporal predicates per model | 65,536 | 1–65,536 |

Input reservation measures the full provider wire conservatively, not actual tokenizer usage. The selected provider/model must support the requested limits. These are operating bounds, not spending allowances. Per-request catalog working sets, source/fact counts, bytes, local compute and finite workflow call counts remain separate. See [Execution bounds](LIMITS.md).

## Saving and persistence

One Save applies validated values atomically. No restart, connection test or provider request occurs. The durable registry record overrides startup defaults from `[llm.call]` and `sources.catalog_predicate_limit`. Before a save, those startup values apply. Reading or reloading the page never creates an override. A paired service backup includes settings; a model snapshot does not change the destination installation’s settings.

New work captures the policy at creation. Existing tasks, connection tests, grants, feeds and identical request replays keep their captured limits, including reservations and deadlines. Newly submitted clarification continuations capture current settings. Lowering the predicate cap does not truncate or invalidate accepted knowledge or prevent snapshot reads/imports. An existing catalog above the configured cap can remain unchanged; adding identities is refused until the cap permits growth. Started Teach tasks retain their captured growth cap. Historical tasks without that field retain the structural ceiling of 65,536. Direct policy changes check growth at entry.

The console has no background form refresh. Invalid saves leave the draft and all saved values intact. Concurrent edits return a clear reload message; **Reload saved settings** discards the draft. An identical save replay succeeds without creating another revision.

Historical Ask/Teach work that has no captured shared call policy stops before a new provider stage with `stale_context`; saving Settings cannot retroactively authorize it. Its records, accepted knowledge and existing grant accounting are preserved. See [retained-work limits](LIMITS.md#shared-provider-call-policy).

## API

`GET /api/v1/settings` returns `revision`, current `values` and startup `defaults`. `PUT /api/v1/settings` accepts:

```json
{
  "expected_revision": 0,
  "values": {
    "llm_call": {
      "max_input_tokens": 256000,
      "max_output_tokens": 32768,
      "max_duration_ms": 360000
    },
    "catalog_predicate_limit": 65536
  }
}
```

Use the revision returned by GET. A different concurrent edit returns HTTP 409 `settings_conflict`; invalid values or incompatible derived workflow bounds return HTTP 422. Successful saves return the current record. The normal local-access and cross-origin protections apply. The project plugin does not expose a settings mutation tool.

Owned schema 19 adds a singleton settings record transactionally. Existing model artifacts, history, evidence, connection credentials and provider accounting are preserved. Old binaries cannot open the newer store; rollback requires the corresponding pre-upgrade paired backup.
