# Priced allowances and isolated provider lanes

Priced allowances provide explicit financial authority and separate scheduling lanes for interaction and learning. The current owned schema is 15. Development verification uses recorded/simulated providers; a new installation begins with spending and remote calls disabled.

## Authority and resources

All amounts are integer micro-US dollars: 1 USD = 1,000,000 units. Prices and allowances are explicit owner resources. Neither source text nor provider output can create them. There is no default dollar allowance, automatic refill, model selection or paid connection test.

1. Configure an installation lifetime cap, protected interaction/learning portions and, where needed, a conservative legacy hold. Their sum cannot exceed the installation cap. Raising a cap requires another owner configuration with the current generation.
2. Install an immutable price record bound to an exact provider connection version/digest, model, counting profile, rates and expiry. A replacement revokes the old price for new dispatch; existing charges retain their original valuation.
3. Create a scoped allowance against that price. Its full cap is allocated atomically from the corresponding installation portion. Concurrent allocations cannot spend the same available capacity. An allowance cannot be enlarged, transferred to another ADM or silently assigned a new price.
4. Reserve each child before its per-ADM handoff, and each call before it becomes visible to a worker. The final grant and monetary charge reservation share one registry transaction. The per-ADM inbox and gateway dispatch store remain separate, reconciled transactions.

| Scope | Permitted provider work | Maximum expiry |
| --- | --- | --- |
| Interaction, bound to an ADM | Interpretation, Ask narration, genuine intent/budget clarification | 24 hours |
| Task, bound to an ADM | Preparation, acquisition, extraction, repair, task completion narration | 1 hour |
| Source, bound to an ADM | Bounded supplied-source learning and its completion narration | 24 hours |
| Control, installation only | Explicit connection test | 1 hour |

The current control allowance charges the installation learning portion and runs in its background slot. It cannot use the protected interaction slot. Scope IDs identify the owner's intended operation. Conversation and teaching coordinators attach their immutable specifications and exact decisions.

Task/source allowances protect one completion call, the verified input bound, 4,096 output tokens and their maximum estimated charge. Those token/call holds also count against installation and ADM quotas before other calls can consume them. The protected room is within the parent cap. A summary reservation can be used only once, including an unknown or failed outcome. Failure to narrate creates no retry of learning or local execution. Ask and teaching completion provide separately labeled narration with an authoritative local fallback.

Existing AWM-ADM episode, interpretation, extraction and connection-test inputs accept an optional `allowance_id`. Real remote work requires it; unpriced recorded fixtures still run without egress. Ordinary AWM-ADM local queries, preview confirmation, admission and snapshots retain their contracts. Empty optional fields are omitted from normalized identities so old unpriced idempotent submissions remain recognizable.

## Conservative pricing profile

A reservation is the sum of two independently rounded-up products:

`ceil(input_bound × input_rate / 1,000,000) + ceil(output_cap × output_rate / 1,000,000)`.

Rates are microdollars per million tokens. Settlement uses provider-reported total input/output tokens at the pinned rates. Cached-input discounts are deliberately ignored; this is a conservative estimated token charge, not a provider invoice. Failed calls with usable usage are still charged. Provider account credits, taxes and unrelated account traffic are outside the installation ledger.

Supported code profiles:

- `recorded-test/1`: synthetic 32,000-input bound, usable only with the recorded no-egress adapter. Test rates of $2/$4 per million reserve 96,768 microdollars for 32,000 input plus 8,192 output, and settle 2,800 for reported 1,000 input plus 200 output. These are not live prices.
- `openai-4o-context/2026-11-08`: a deliberately conservative reference profile for exactly `gpt-4o-2024-08-06`, text-only Responses, standard service tier, no tools/media/sessions. It reserves the full documented 128,000-token context as the input bound, plus the requested output cap, at no less than $2.50 input/$10 output per million. The entire context bounds billable input, including instructions/schema/framing; wire byte length is not used as the proof. This may reserve much more than the eventual usage. The configured per-call input cap must explicitly permit 128,000; the normal 32,000 default is insufficient. Rates expire within 30 days and the audited profile expires on 8 December 2026.


- `openai-5.6-luna-context/2026-11-09`: exactly `gpt-5.6-luna`, text-only Responses at the fixed OpenAI endpoint, standard tier and the same closed wire. Reserve the entire **1,050,000-token context** as input. Conservative rates are **$0.50 input / $1.80 output per million**, covering the long-context and default cache-write multipliers. Price expiry cannot exceed 8 December 2026. This profile establishes bounded accounting, not model availability or answer quality.

The [Luna model specification](https://developers.openai.com/api/docs/models/gpt-5.6-luna), reviewed 9 November 2026, lists $0.20/$1.20 base rates and applies 2× input and 1.5× output above 272,000 input tokens. [Prompt caching](https://developers.openai.com/api/docs/guides/prompt-caching) specifies a default 30-minute cache-write rate of 1.25× input for this generation. Thus the input ceiling is $0.20 × 2 × 1.25 = $0.50, and output is $1.20 × 1.5 = $1.80. Apply these conservative rates to all reported input/output; do not add cache-write token subtotals again. The closed wire forbids `prompt_cache_options` (including costlier 12-hour retention), tools and nonstandard tiers. Pricing is exact-configuration metadata; it does not branch acquisition guidance or local acceptance on the model name.

New conversational allowance proposals disclose the selected audited per-call input bound and six-call total before owner acceptance. Ask/clarification use only that approved bound; older approvals retain 32,000 when the field is absent. Teaching children and managed source extraction remain inside the parent and explicit operator limits. The normal installation input cap is 32,000 per call; operators must explicitly configure limits sufficient for their selected audited profile before using it. Hard maximum input is 1,050,000/call and 21,000,000 per allowance (20 calls), not automatic permission to spend it.

The reference profile's context, prices, snapshot identifier and structured-output support were checked against the [OpenAI model page](https://developers.openai.com/api/docs/models/gpt-4o). That page marks this model deprecated, rather than shut down; this is not a model recommendation or evidence of access for any particular account. The [context-window documentation](https://developers.openai.com/api/docs/guides/conversation-state) specifies that the context limit includes input, output and reasoning. Published specifications do not establish live availability for a configured account.

Other model/configuration combinations fail with an actionable unsupported-price/bound error. Saving a provider connection does not install a price or grant spending authority. The [token-counting API](https://developers.openai.com/api/docs/guides/token-counting) is a possible future tighter bound, but its pricing, exact structured-output coverage and separate call/disclosure authority need verification before implementation. It is not called by the runtime. Renew pricing evidence or add a supported audited profile before a live trial. Prompts, grammars, task meaning and local admission remain model-neutral.

## Uncertainty, recovery and overruns

| Event | Durable accounting and behavior |
| --- | --- |
| Known nonzero remote usage | Settle at pinned rates; release unused call reservation once |
| Missing/invalid usage, remote 0/0, timeout or unknown dispatch | Retain the full monetary and token reservation; 0/0 is not a free call |
| Proven not dispatched (for example stale ready grant) | Release its call reservation; retain audit identity |
| Known token/money overrun | Charge the reported amount in full; suspend affected provider lane and overrun allowance; other funded lane stays usable |
| Price/connection/authority changes | Fence pending dispatch; never rewrite an old charge or enlarge authority |
| Allowance close/expiry | Release only provably unspent allocation; unsettled reservations and settled charges continue consuming installation capacity |
| Restart | Reconcile durable grants/charges; unfinished dispatched work stays unknown; no automatic external retry |
| Paired restore | Preserve all counters and holds; disable paid/remote authority and revoke operational credentials |

Owner spending configuration can explicitly list `resume_lanes` after reviewing an overrun and ensuring caps cover retained charges. This does not resume a suspended allowance, change its price or repeat its work. Configuration generations and their submitted values are retained in a bounded history.

Schema 9 records pre-existing remote grant IDs as `unpriced_legacy` without rewriting their original counters/outcomes or assigning fabricated money. New paid authority requires a positive conservative owner hold against the installation cap. This allocation is not a reconstructed invoice. The hold cannot be lowered through ordinary settings, expiry or a new allowance. Evidence-based legacy reconciliation is a later administrative operation, not a guess by migration code.

Child work reservations are persisted before handing off to an ADM store. Exact operation replay recovers its existing reservation/grant; changed content under the same identity fails. An orphan or unknown child retains work capacity. Checked local work can settle through the internal ledger API; automatic child reconciliation and completion are performed by the teaching coordinator. This favors a visible conservative stop over duplicate spending.

## Scheduling and local execution

The default runtime has two provider slots, one for interaction and one for background work, with round-robin ADM selection and FIFO within an ADM. Background learning cannot occupy the reserved interaction slot. One ADM may have one call in each lane. Two existing worker threads allow those calls to progress concurrently. Connection tests use background capacity. The gateway retains its process deadline and at-most-once outbound dispatch record.

The default 24-hour token/call partitions are the [AWM-ADM limits](LIMITS.md): 40% interaction and 60% learning of the existing installation/ADM totals. Both the total and the lane partition apply. Unknown calls remain counted after the period. Lower operator quotas can reduce availability; priced lanes require at least two configured provider slots globally and per ADM. Provider-account throttling and a global owner remote-disable action remain shared external/administrative constraints.

Local serving retains its two bounded compute slots. Language/catalog checking now has its own one-slot supervisor; learning/source checking keeps the background supervisor. The finite engine, owner conformance, revision bindings, forward/backward conflict rules and proof assurance are unchanged.

## API and details

All financial routes require owner authentication and existing same-origin/CSRF protections:

- `GET/PUT /api/v1/spending`: configuration, generation, committed lane usage, unknown legacy count and suspended lanes.
- `GET/POST /api/v1/prices`: immutable price installation and bounded browsing.
- `GET/POST /api/v1/allowances`: explicit scoped allocation and bounded browsing.
- `GET /api/v1/allowances/{id}` and `POST .../{id}/close`: current accounting and conservative closure.

Lists accept `after` (sequence cursor) and `limit` (1–100, default 20). Grant Details include lane and price/allowance binding. Allowances separate estimated settled charges, retained reservations and unknown amounts; synthetic valuations are labeled. Connections exposes installation ceilings and an exact pricing review. `GET /api/v1/connections/{id}/price-options` lists only currently supported audited configurations, requires owner authentication and dispatches nothing. Choosing Install this price invokes the same exact-version API; no unsupported model gains pricing through the UI. Ask/Teach ask for their own budget in conversation. Settings are administrative controls, not task-parameter forms.

## Retained teaching review

An owner can explicitly renew time for an unchanged, unstarted checked preparation, at most one hour per confirmation and eight times per task, within price validity. The same allowance retains all charges and original financial/call/token/work caps. Unknown calls, closed authority, changed context/configuration and insufficient installation room prevent renewal. The registry operation journal records the original and renewed expiry atomically with accounting; applying it to the task is idempotent. No existing grant deadline is altered and no work starts automatically. See [teaching execution](TEACHING_EXECUTION.md).
