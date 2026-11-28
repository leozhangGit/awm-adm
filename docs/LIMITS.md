# Execution and storage bounds

Ordinary use requires no monetary allowance, spending form or financial expiry. Finite execution bounds prevent unbounded provider loops and protect local serving capacity. Console, plugin and API requests share the same policy.

The console’s [Settings page](SETTINGS.md) edits the three shared call limits and the accumulated predicate cap. Saved installation values override startup configuration without a restart; new work captures those values.

## Shared provider-call policy

```toml
[llm.call]
max_input_tokens = 256000
max_output_tokens = 32768
max_duration_ms = 360000
```

All provider purposes use this profile: Ask interpretation/explanation, Teach preparation/acquisition/completion, source extraction, feeds, advanced interpretation and connection testing. Ask remains read-only; Teach can publish only locally validated knowledge. No stage-specific cap overrides the common settings.

| Limit | Default | Hard ceiling |
| --- | ---: | ---: |
| Input reservation per call | 256,000 units | 1,050,000 |
| Output per call | 32,768 tokens | 100,000 |
| Provider execution per call | 360 seconds | 600 seconds |
| Ready-dispatch queue wait | 60 seconds | Shared internal rule |
| Finite workflow finishing allowance | 60 seconds | Shared internal rule |
| Worker delivery grace | 3 seconds | Does not extend provider execution |

The complete UTF-8 provider request plus 4,096 framing units is measured before reservation. Instructions, schema, selected history, model context, material and checked feedback all count. This is a conservative estimate, not measured tokenizer usage or a promise about a provider's context window. An oversized request stops before dispatch with required/available figures; it cannot enlarge its cap or silently truncate evidence. Output is a ceiling, not a required response length or expected bill.

Omitted and partially specified API limits resolve from installation policy. Explicit smaller limits remain effective; larger values are refused. Complete values are captured before scheduling. Existing jobs, feeds, grants and same-identity replays retain their original limits. Historical serialized CallLimits defaults do not configure new requests.

Retained Ask/Teach work without a captured shared policy cannot authorize a new provider stage. It stops with `stale_context` instead of borrowing today's settings; accepted knowledge, existing grant accounting and the original submission identity remain intact. Review the retained outcome before deliberately submitting a new request. Replaying the old identity does not restart it.

## Aggregations

For a finite operation permitting N calls, default input/output envelopes are N times the per-call ceiling. Its duration is N times (60 seconds plus per-call duration), plus 60 seconds of finishing allowance. Existing attempt, child, item, no-progress and local-work bounds remain independently effective. Capacity does not cause extra calls or retries.

| Operation | Calls | Input ceiling | Output ceiling | Outer duration |
| --- | ---: | ---: | ---: | ---: |
| One provider operation | 1 | 256,000 | 32,768 | 8 minutes |
| Ordinary Ask or automatic acquisition child | 2 | 512,000 | 65,536 | 15 minutes |
| Explicit default learning episode | 3 | 768,000 | 98,304 | 22 minutes |
| Six-call source batch | 6 | 1,536,000 | 196,608 | 43 minutes |
| Twenty-call finite batch | 20 | 5,120,000 | 655,360 | 141 minutes |

Teach captures a finite root envelope before preparation and narrows it to the checked plan: one preparation, up to four children, then one completion explanation. Acquisition children permit two calls; source children six. Four acquisition children give ten calls and a 71-minute ceiling. The largest source-heavy plan permits 26 calls, 6,656,000 input units, 851,968 output tokens and 183 minutes. These are worst-case bounds, not typical waiting times or promises of learning success. Work finishes as soon as it completes or cannot continue.

A dispatch is counted once against each applicable parent and once in global usage. Known usage settles the global reservation, including failed known calls. Unknown dispatched calls retain reservations. Smaller explicit aggregate budgets stay effective. A new call is refused if its parent cannot fit the captured execution and delivery time; it is not squeezed into the parent's final seconds.

Standing feeds may wait for material without a provider timeout running. Their lifetime item/call/token/work bounds stay finite. A default twenty-call feed derives 5,120,000 input and 655,360 output units; local-work limits may permit fewer items. Each processing unit has bounded queue/execution time; Teach-managed feeds also obey their finite parent. Feed lifetime reservations are conservative and are not refunded.

Derived feed token envelopes must also fit the public feed schema's lifetime bounds. An oversized envelope is refused before creating work, with `aggregate_exhausted` and required/available values. Call count is a ceiling, not a guarantee: explicit smaller lifetime token budgets may stop the feed before that many calls.

## Timing and diagnostics

A ready grant gets a sixty-second queue deadline. Provider expiry starts at claim and cannot be renewed by restart or redispatch. Undispatched expiry is queue_timeout, with no provider charge. Aggregate exhaustion is distinct from provider_timeout. The gateway bounds the whole transport, including response reads. A gateway_wait timeout identifies where waiting ended, not whether networking, scheduling or generation caused it.

Claim also captures a result-delivery deadline three seconds after provider expiry, bounded by the parent deadline. This allows an in-flight callback to arrive without racing the application's timeout sweep; it cannot authorize execution after provider expiry. After the delivery deadline, a completed response may settle known usage but cannot supply new knowledge or an answer. Retained leases without this field keep their original expiry.

Human clarification waits do not expire financial authority. An explicit reply starts a bounded continuation, without retrying an uncertain call. Polling, configuration changes and restart make no provider request.

Safe capacity diagnostics report scope, required/available values and provider_call_dispatched: false. Dispatch reads expose execution_limits with captured call, queue/aggregate deadlines, provider expiry and delivery deadline where known. Provider diagnostics retain measured timing and reported usage separately. Historical unknown fields remain unknown. See [provider failures](PROVIDER_FAILURES.md).

## Other independent bounds

| Area | Current behavior |
| --- | --- |
| Direct input | 65,536 characters; HTTP JSON body at most 2 MiB |
| Selected context | Six prior owner turns / 16 KiB, same model and channel |
| Attachments | UTF-8 Markdown/text/JSON/JSONL; 256 KiB original bytes each; finite selected scope |
| Provider transport response | 2 MiB; semantic schema/content bounds still apply |
| Local request | One million work units / ten seconds by default; managed phases use up to five seconds where specified |
| Serving/background | Separate bounded process capacity and fair scheduling |
| Intake | Finite backlog, item/call/token/work reservations, throttling and explicit stop/finish |
| Storage | Finite records and bytes; refuse new work instead of discarding accepted evidence |

Compute, Lean, SQLite locking, asynchronous HTTP, health checks, process leases, shutdown and credential lifetimes are separate. A plugin HTTP request need not remain open for six minutes. Local reasoning, search and proof defaults are unchanged. Resource exhaustion is inconclusive, not a contradiction or proof of impossibility.

Configuration uses awm-adm-config/3. Convert an older file offline with `.venv/bin/python scripts/convert_llm_config.py old.toml new.toml`, then review the mapping and validate the new file. Custom legacy limits require all three explicit choices: --input-reservation, --output-tokens and --timeout-seconds. Original files and retained work are not modified; mixed old/new keys are refused. No active daily financial/call/token quota gates new work. Historical accounting and lifecycle specification records remain available.

## Temporal evidence

The accumulated temporal catalog has a configurable growth cap, default and hard ceiling 65,536, for unique predicates, 128 entities and 256 normalized scopes. It is a sparse registry, not a Cartesian set of asserted facts. A single proposed Teach mapping remains bounded to 32 predicates and 4,096 possible addresses. These working-set limits do not constrain the accumulated predicate count. Capacity failures expose existing/proposed/shared/required counts without echoing the submitted content.

Preparation and Ask expose at most 256 policy predicate descriptors with explicit completeness metadata; Ask retains up to 32 relevant snapshot metadata profiles within 32 KiB, explicitly marking partial coverage; lexical selection is a retrieval hint, not exhaustive semantic matching. Teach supplies its selected predicates to extraction. Direct extraction and feeds accept optional `catalog_predicates` (1–256 distinct known symbols). Larger external extraction without a selection stops before dispatch; it never silently drops source coverage. New temporal bindings retain only the descriptor/entity/scope needed for that fact, preserving exact identities and old artifacts.

An extraction has at most 100 claims and a collection page at most 100 items. Exact replacement can retain at most 32 dependent definitions. Existing source, fact, byte, snapshot, language-catalog, work/time and task limits remain independent: 65,536 is a predicate-count ceiling, not a guarantee that any catalog of that size fits every configuration or that an entire large codebase can be analyzed in one call. Exhaustion remains explicit and inconclusive. Legacy projection profiles keep their existing bounds and serving paths.

A checked reaffirmation child makes no acquisition call. Its root provider envelope counts preparation and completion plus any other learning/source children; local compute, retained receipt, snapshot and evidence-size limits still apply.
