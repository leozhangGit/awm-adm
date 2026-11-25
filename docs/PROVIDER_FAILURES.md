# Provider deadlines and failure diagnostics

An enabled connection can have an unsuccessful call without being disabled. Read the retained dispatch outcome and locally measured diagnostics; a failed preparation is not a rejection of the supplied knowledge by the algebraic engine.

## Preparation time

Teaching preparation has its own `learning.preparation_timeout_ms` installation bound, default **180,000 ms (three minutes)**, allowed from 1 through 300,000 ms. It applies to every domain, provider and model. Acquisition has a separate three-minute bound described below. Ask, narration, extraction and connection tests use the ordinary per-call limit, normally 60,000 ms. Token, concurrency and local compute limits are separate from these deadlines.

The three-minute setting bounds a new preparation grant; its deadline is the earlier of that bound from reservation and the exchange's existing five-minute active-work deadline. Claim and dispatch cannot extend it. The gateway's actual remaining deadline may therefore be shorter than the configured limit. The worker waits for that grant's duration plus its existing delivery grace; the gateway bounds the complete child process, including response reads. A longer deadline is not a guarantee that a provider will complete a plan.

New configuration defaults apply to new preparation work. Retained grants keep their original limits and identity; upgrades never extend, replay or reclassify an uncertain historical call. Waiting for a semantic clarification is separate from running work and requires no spending permission renewal.

## Acquisition time

Acquisition uses `learning.acquisition_timeout_ms`, default **180,000 ms**, allowed from 1 through 600,000 ms. Explicit episodes use a three-minute call default and check submitted limits against that installation cap. The general episode allows up to 12 minutes for its bounded attempts and local checking. Automatic Teach captures a child deadline no later than the remaining 15-minute execution deadline and clips each call accordingly. At claim, the execution lease is the earlier of the captured call duration and the episode deadline; the gateway enforces the remaining time for its complete child process. Worker RPC delivery grace does not extend that execution deadline.

Input capacity and elapsed time are independent limits: a larger request cap does not imply proportionally longer execution or a larger output allowance. `provider_timeout` with `failure_stage: gateway_wait` identifies an expired wait without identifying whether generation, networking or provider processing caused the delay. It retains `outcome_unknown` and the original reservation. Older grants keep their limits, and a restart or longer default never retries them. Accepted independent Teach children remain accepted even if a later acquisition times out.

## Extraction queue and execution bounds

New extraction jobs allow up to 60 seconds waiting for dispatch, separately from their configured per-call duration (normally 60 seconds). Their overall deadline is the earlier of creation plus both bounds and the owning task deadline. The grant retains that overall bound; its execution lease starts when claimed and is clipped to the remaining overall deadline. Queue waiting therefore does not consume the per-call duration while sufficient overall time remains. Queue expiry is `queue_timeout` and `not_dispatched`, with no call charge. Existing grants retain their original deadlines; leased/dispatched work is never renewed or automatically retried.

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
