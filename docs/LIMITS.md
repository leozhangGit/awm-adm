# Execution and storage bounds

Ordinary use requires no monetary allowance or financial expiry. Finite execution bounds prevent a request from becoming an unbounded provider loop or exhausting local serving capacity. These are internal operating defaults, not forms the user must fill out.

| Area | Current behavior |
| --- | --- |
| Direct input | At most 64 KiB text; bounded JSON body of 2 MiB |
| Automatically selected context | At most six prior owner turns / 16 KiB; same model and channel |
| Attachments | UTF-8 Markdown/text/JSON/JSONL, 256 KiB original bytes each; preparation checks its selected material scope |
| Provider call | Configured input capacity; normally at most 8,192 output tokens and 60 seconds; preparation uses its separate bound; Ask/narration may use smaller output caps |
| Preparation | Three-minute provider deadline (`learning.preparation_timeout_ms`), capped by the exchange's five-minute active-work deadline; idle semantic clarification does not expire a spending permission |
| Teaching execution | Normally 15 minutes of active work, bounded children and attempts; two unsuccessful acquisition attempts stop rather than looping |
| Local phase | At most one million work units / five seconds where the task profile uses these bounds; smaller installation limits apply |
| Serving/background | Separate bounded process capacity; round-robin scheduling across ready models |
| Managed intake | Bounded backlog, finite item/call/token/work reservations, producer throttling and explicit stop/finish; see [Intake](INTAKE.md) |
| Retained history | Finite per-model records and installation bytes; refuse additional work rather than silently discard accepted evidence |

`config/default.toml` and `deploy/config.toml` contain installation ceilings. `CallLimits` and task/source schemas define hard input bounds. Internal token estimates bound requests and scheduling; they are not price certificates. There is no per-day financial, call or token quota blocking new independent work after an earlier task.

An execution deadline bounds running work. It is distinct from waiting for a human clarification. Unknown dispatched calls retain identity and usage uncertainty even after a deadline, cancellation, restart or calendar boundary. There is no automatic retry, model switch, refill or promise to acquire missing knowledge. Known tokens, including failed calls, are reported in Connections; unknown usage is shown separately.

Accepted local requests use the finite engine's reasoning, search, proof and work defaults. A resource stop is inconclusive, not a logical contradiction or proof of impossibility. Structured request APIs and library interfaces expose these capabilities independently of the chat console.

The versioned files in `contracts/workflows/` retain the original finite lifecycle/arithmetic specification profiles for compatibility and historical accounting checks. Their financial examples do not configure current dispatch. Current interaction cases are in [`interaction-corpus.json`](../contracts/interaction-corpus.json); actual transports are in [OpenAPI](../contracts/openapi.json).

## Temporal evidence

Temporal catalogs are cumulatively bounded to 128 entities, 32 predicates, 256 normalized scopes and 4,096 Cartesian addresses. An extraction has at most 100 claims and a collection page at most 100 items. Existing configured source, work/time, disclosure and task limits still apply. Exact replacement can retain at most 32 dependent definitions. Valid larger legacy catalogs retain their existing serving path; an oversized extension cannot rewrite them.
