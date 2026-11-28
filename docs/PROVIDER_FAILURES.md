# Provider deadlines and failure diagnostics

An enabled connection can have an unsuccessful call without being disabled. Read the retained dispatch outcome and locally measured diagnostics; a failed preparation is not a rejection of the supplied knowledge by the algebraic engine.

## Shared call and workflow deadlines

Every provider purpose uses [the common policy](LIMITS.md): 256,000 conservative input units, 32,768 output tokens and 360,000 ms of provider execution by default. Explicit smaller limits remain effective; above-ceiling values are refused.

A ready grant has sixty seconds to obtain dispatch. Claim starts its provider expiry without subtracting queue wait. The parent must fit the complete call plus three seconds of RPC delivery; otherwise the call is refused as aggregate exhaustion. The gateway enforces the whole-call deadline, including response reads and child termination. Delivery grace does not extend execution.

The application captures a separate result-delivery deadline at claim: provider expiry plus three seconds, bounded by the parent. Its timeout sweep waits until that deadline so a returning timeout or completed response can be recorded consistently. Authorization still stops at provider expiry. After the delivery deadline, known usage can settle, but a successful payload becomes `dispatch_expired` and cannot publish or answer. An uncertain call is never automatically repeated. Retained leases without a delivery deadline use their original expiry.

Finite workflows derive deadlines from locally permitted calls: N times (queue wait plus provider duration), plus finishing allowance. A two-call Ask permits fifteen minutes overall; a three-call episode twenty-two. Teach narrows its envelope to its checked plan. These are ceilings, not expected durations or retries. Accepted independent children remain accepted when later work fails. Human clarification is separate; retained work keeps its captured limits.

## Extraction output, queue and execution bounds

Teach, intake, feeds and direct extraction APIs use the same profile. Six-call Teach source feeds derive 196,608 output tokens; a default twenty-call feed derives 655,360. Each item reserves its captured call ceiling. Smaller explicit budgets and independent local-work bounds stay effective. Standing feeds do not expire merely while waiting for material.

Known usage settles global accounting even on failure; unknown dispatched outcomes retain reservations. Feed lifetime reservations remain conservative and are not refunded. Queue expiry is queue_timeout / not_dispatched with no provider charge. Insufficient parent capacity is aggregate_exhausted. Dispatch reads expose execution_limits with call limits, queue/aggregate deadlines, provider expiry, delivery deadline and observed dispatch flag.

An output_incomplete response reporting max_output_tokens reached its captured output allowance, including provider-counted reasoning where applicable. No incomplete response is admitted, even if a fragment resembles complete JSON. A larger bound does not guarantee completion or renew/retry historical work.

## Retained diagnostics

The gateway adds optional, allowlisted fields to provider outcomes:

| Field | Meaning |
| --- | --- |
| `transport_failure` | Timeout, DNS, TLS, connection, HTTP protocol, response-size, unclassified transport or gateway child-process failure |
| `failure_stage` | Request, response headers/body, transport, response interpretation, gateway start/wait/output |
| `elapsed_ms` | Locally measured elapsed time, using a monotonic clock; the gateway includes its child-process wait |
| `timeout_ms` | Actual time available to that call when the gateway starts it |
| `http_status` | Only a status actually observed, including when reading its response later fails |
| `child_exit_code` | Only an observed child return code; a signal does not establish why the process was killed |

Timeouts report `provider_timeout`. Other incomplete transport/process outcomes retain `transport_uncertain` with the narrower diagnostic reason. Known HTTP failures retain their existing distinctions: authentication, insufficient quota, rate limiting, invalid request/model and provider errors. Output-token exhaustion remains `output_incomplete`, distinct from elapsed-time exhaustion.

No arbitrary exception messages, response bodies, credential-bearing URLs, headers or hidden reasoning are retained. The diagnostics describe what the service observed; they cannot prove whether the provider continued processing or charged for an interrupted request.

## Source completion diagnostics

Source execution retains bounded child diagnostics in `teaching.summary.source_failures` and the interaction's `failure_diagnostics`. Each entry identifies the objective, source item, job/grant, safe reason and available provider outcome/usage. Completeness flags expose truncation. The existing plugin passes the same packet through its work result.

An empty extraction is `empty_extraction`: no claims were returned, and no explanation is inferred from that absence. A timed-out call is distinct from missing evidence or coverage, invalid output, and queue expiry. Skipped vocabulary installation after an unresolved child is reported as a consequence of incomplete learning. Accepted independent objectives remain accepted; narration cannot convert unresolved work into success. Historical failures without retained details stay generic.

## Teach and plugin presentation

Teach retains the failure code and a readable explanation in its chat, task and interaction history. `failure_diagnostics` includes the grant identity, dispatch status, configured timeout, provider diagnostics, any known usage, unresolved-usage flag and `automatic_retry: false`. The existing plugin passes this record through without another call or a change to its tool signatures. The message distinguishes a timed-out call from a disabled connection and states that no learning started or knowledge was accepted during failed preparation.

Unknown completion remains `outcome_unknown` in the dispatch ledger even though its containing preparation finishes as `failed`. Unknown usage retains the original reservation. Known usage from a failed response is still counted. Neither polling, an identical submission, a restart nor the longer preparation default creates a retry. An explicit new attempt is separate work.

Historical generic diagnostics remain generic. A failure that lacks recorded timing or a timeout reason must not be retrospectively asserted to have timed out.

All preparation-plan, source, temporal, finite-type, owner-requirement, dependency and admission validation stays authoritative. These transport diagnostics do not relax any model check.
