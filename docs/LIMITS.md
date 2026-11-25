# Execution and storage bounds

Ordinary use requires no monetary allowance or financial expiry. Finite execution bounds prevent a request from becoming an unbounded provider loop or exhausting local serving capacity. These are internal operating defaults, not forms the user must fill out.

| Area | Current behavior |
| --- | --- |
| Direct input | At most 64 KiB text; bounded JSON body of 2 MiB |
| Automatically selected context | At most six prior owner turns / 16 KiB; same model and channel |
| Attachments | UTF-8 Markdown/text/JSON/JSONL, 256 KiB original bytes each; preparation checks its selected material scope |
| Provider call | Default input reservation cap 128,000 and at most 8,192 output tokens. Acquisition has a three-minute limit (`learning.acquisition_timeout_ms`); Ask, extraction, narration and connection tests retain the ordinary 60-second cap. Ask/narration may use smaller output caps. |
| Learning episode | General default: at most three calls, 384,000 aggregate input reservation and 12 minutes. An automatic Teach acquisition child uses at most two calls and 256,000 aggregate input reservation, within 12 minutes or the parent's remaining time, whichever is shorter. Smaller explicit caps remain effective. |
| Preparation | Three-minute provider deadline (`learning.preparation_timeout_ms`), capped by the exchange's five-minute active-work deadline; idle semantic clarification does not expire a spending permission |
| Teaching execution | Normally 15 minutes of active work, bounded children and attempts; two unsuccessful acquisition attempts stop rather than looping |
| Local phase | At most one million work units / five seconds where the task profile uses these bounds; smaller installation limits apply |
| Serving/background | Separate bounded process capacity; round-robin scheduling across ready models |
| Managed intake | Bounded backlog, finite item/call/token/work reservations, producer throttling and explicit stop/finish; see [Intake](INTAKE.md) |
| Retained history | Finite per-model records and installation bytes; refuse additional work rather than silently discard accepted evidence |

`config/default.toml` and `deploy/config.toml` contain installation ceilings. `CallLimits` and task/source schemas define hard input bounds. Internal token estimates bound requests and scheduling; they are not price certificates. There is no per-day financial, call or token quota blocking new independent work after an earlier task.

The acquisition input estimate counts the complete UTF-8 provider request plus 4,096 units of framing allowance. It includes instructions, response schema, selected user material, accepted model context and checked feedback. This conservative estimate is not a measured tokenizer count or a promise about a provider's context window; unused capacity does not pad the request. Each explicit episode retains its submitted caps, and each Teach child captures its per-call bound and two-call aggregate bound when created. Configuration changes do not expand retained work or restart failed episodes.

An over-cap acquisition request stops before a grant is created or a call dispatched. The episode retains `reason: invalid_limits` and a safe `failure_diagnostics` record with `code: input_capacity_exceeded`, required/available input reservations, `measurement: conservative_input_estimate` and `provider_call_dispatched: false`. Teach summaries and interaction/API/plugin reads preserve the child diagnostic; chat explains the limit in plain language. The dispatch statement applies to this rejected call, not earlier preparation, learning or narration calls. No prompt, credential or arbitrary exception text is copied into the diagnostic. Historical failures without these fields remain unknown rather than receiving reconstructed figures.

An execution deadline bounds running work. It is distinct from waiting for a human clarification. Unknown dispatched calls retain identity and usage uncertainty even after a deadline, cancellation, restart or calendar boundary. There is no automatic retry, model switch, refill or promise to acquire missing knowledge. Known tokens, including failed calls, are reported in Connections; unknown usage is shown separately.

Acquisition time is independent of request size: a larger input cap does not imply proportionally longer execution or more output tokens. `learning.acquisition_timeout_ms` defaults to 180,000 ms with a hard range of 1–600,000 ms. Explicit episode call limits are checked against it; automatic Teach captures the smaller of that cap and its remaining child time. At dispatch the lease and gateway whole-call deadline are further bounded by the episode deadline. The worker RPC allows the grant's call duration plus three seconds for delivery; this grace does not extend provider execution. A `provider_timeout` at `gateway_wait` records where the wait ended, not whether the underlying delay came from the provider, network or generation. Increasing a default neither revises an old grant nor retries it.

Accepted local requests use the finite engine's reasoning, search, proof and work defaults. A resource stop is inconclusive, not a logical contradiction or proof of impossibility. Structured request APIs and library interfaces expose these capabilities independently of the chat console.

The versioned files in `contracts/workflows/` retain the original finite lifecycle/arithmetic specification profiles for compatibility and historical accounting checks. Their financial examples do not configure current dispatch. Current interaction cases are in [`interaction-corpus.json`](../contracts/interaction-corpus.json); actual transports are in [OpenAPI](../contracts/openapi.json).

## Temporal evidence

Temporal catalogs are cumulatively bounded to 128 entities, 32 predicates, 256 normalized scopes and 4,096 Cartesian addresses. An extraction has at most 100 claims and a collection page at most 100 items. Existing configured source, work/time, disclosure and task limits still apply. Exact replacement can retain at most 32 dependent definitions. Valid larger legacy catalogs retain their existing serving path; an oversized extension cannot rewrite them.
