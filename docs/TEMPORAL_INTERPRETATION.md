# Meaning, representation and temporal context

Ask, Teach preparation and source extraction share model-neutral guidance: resolve the intended meaning from the supplied context, then encode supported typed fields. A formatting requirement is not a missing fact. Preserve identity, units, scope and precision; clarify uncertain meaning and report unsupported representations without inventing content to fit a schema. Domain rules and examples belong to model instances.

An exact named clock instant uses a second-resolution coordinate; omitted lower clock components do not by themselves make it an uncertain observation. Approximate or rounded times retain supported windows and source precision. Shared guidance and schema descriptions explain this distinction in preparation, extraction and Ask; they do not infer unavailable bounds or change local scope validators.

## System timezone

An explicit relevant timezone in the user's request or linked user context takes precedence. Otherwise the service supplies its system timezone automatically, for both console and API interactions. Explicit source timezones retain their meaning. UTC storage encoding and browser display preferences do not choose the timezone of a question.

Native execution resolves an IANA timezone from `TZ`, the system timezone file or `/etc/localtime`. Docker setup captures the host's system timezone in `.local/system-timezone`, mounted read-only into the application. `make runtime-setup` refreshes this file; restart the app after changing the host default. An explicitly invalid or unavailable timezone is an error, not a silent UTC fallback. The system's actual UTC default remains valid. No per-message timezone setting is required.

The default is captured in each Ask work record before dispatch and retained in its provider disclosure. A date interpretation records the selected timezone, whether it was explicit or defaulted, and the resolved UTC bounds. Replaying that work does not recalculate its meaning using a later default. Teach preparation retains its captured timezone in the task; its managed source-extraction children use that same default. Independent extraction jobs capture the current service default in their own disclosure. Existing proposals, sources and results are never rewritten.

## Dates and exact instants

Historical Ask supports exact instants, uncertain occurrences, validity intervals, exact reporting periods and attributed reports. See the [typed temporal contract](TEMPORAL_EVIDENCE.md). A date without a time denotes the whole civil day in the selected timezone, from its start inclusive to the next day's start exclusive. Application code converts these boundaries with IANA timezone rules. A civil day can span 23 or 25 hours at daylight-saving transitions. A skipped or repeated boundary requires clarification rather than an arbitrary fold or offset. Both UTC endpoints must fit the supported datetime range; an overflowing provider date fails that interpretation without submitting a local request or stopping the worker.

For a legacy validity question, the resulting `lookup_fact_period` query carries exact UTC `effective_from` and `effective_to` bounds. Its source-service evaluator checks the accepted, validated snapshot. It requires unique, active interval support covering the entire requested period, and matching computed values, value kinds and units across that coverage. Gaps, overlapping support, point-only evidence and disputes do not establish a period-wide value. Different values within the period produce a request for a narrower time. Coverage metadata alone never establishes a fact, including for a date outside configured coverage.

Existing `lookup_fact` queries retain their exact-instant semantics and encoding. Both queries bind to the actual model revision, support and complete query scope. The finite interpreter evaluates accepted definitions; the period adapter checks temporal coverage. This is service implementation assurance, not a formal proof of the adapter or of external truth. It uses the same request work/time limits; exhaustion remains inconclusive.

A typed query uses the intent that matches the question: day-wide validity, observations within the day, or the value for that exact period. A calendar window is not automatically a persistence assertion. Unknown occurrence time stays uncertain; reporting time and target period stay distinct. The application accepts a civil-day shorthand only for window scopes, never for an exact instant.

## Supplied evidence

Provider-facing source schemas describe canonical instants as `YYYY-MM-DDTHH:MM:SSZ`, inclusive starts and exclusive ends. The strict local timestamp, interval, carrier, source-span and admission validators remain authoritative. A provider's bare date in an instant field is still rejected; the service does not silently add midnight UTC or salvage a malformed proposal.

Source periods retain their intended coverage and explicit timezone. The legacy projection's granularity is a UTC carrier alignment: day/year bounds must be aligned in UTC. Converted local boundaries may require a second-granularity carrier; that encoding does not assert finer evidential precision or turn a period into a point. Source bytes and attribution remain immutable. Provider interpretation and timezone conversion in proposals remain fallible and require application-specific fidelity checks.

## Readable outcomes and verification

Historical chat shows an ordinary explanation plus an independently generated value label marked **Historical evidence**. Missing support, disputed evidence and within-period changes retain distinct readable outcomes. Full query, source support, result bindings and assurance metadata remain available through the API.

Offline tests cover timezone defaults and explicit overrides, DST, invalid dates/zones, skipped boundaries, fixed disclosure after dispatch, complete/partial/disputed coverage, within-period changes, snapshot evidence and unknown follow-ups. They use authored provider replies; they establish orchestration and validation behavior, not natural-language reliability. See [Ask](ASK.md), [sources](SOURCES.md) and [testing](TESTING.md).
