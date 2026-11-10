# AWM-ADM contributor instructions

Read `README.md`, `CONTRIBUTING.md`, `docs/ARCHITECTURE.md` and the relevant feature contracts before substantive work. This repository is the standalone AWM-ADM 0.3.0 product. It must build and test without a parent workspace or private development-history files.

## Product boundaries

- Keep the finite engine domain agnostic. Each instance starts empty or from a checked snapshot; examples belong to fixtures, never shared acquisition guidance or core rules.
- Separate fallible provider acquisition/interpretation/narration from authoritative local execution. Only complete checked candidates can publish. Provider/source output cannot grant authority or change independent owner requirements.
- Preserve model-neutral guidance and authored provider-schema order; canonical model artifacts keep their existing sorted encoding. Model choice is explicit configuration, not a branch in task meaning or validation.
- Preserve exact request/result/revision/policy/support bindings, action-selection intent and separate witness/shortestness/unreachability claims. Lean kernel checks and exhaustive correspondence remain distinct; never accept caller-provided Lean source or silently downgrade a requested check.
- Forward conflict mode prefers later receiver arrivals; backward mode retains earlier arrivals. Receipt sequence is local and monotonic. Mode changes affect future decisions only; replacement checks dependent conclusions.

## Service, authority and accounting

- Keep the public API under `/api/v1`, with preview history at `interpretation-sessions` and Ask/Teach history at `conversations`. Preserve existing serialized profiles and stored formats independently of URL versioning. Product version is 0.3.0.
- Ask/Teach have separate histories/authority. Full JSON belongs in Details/Local debug. Semantic decisions, protected settings and source review require exact owner/context checks; ordinary provider text never authorizes them.
- Preserve durable intents across registry/ADM/gateway boundaries, short atomic publication transactions, generation/expiry/cancellation/deletion fences and at-most-once provider dispatch. Unknown dispatched calls retain reservations and are never automatically repeated.
- Keep separate priced interaction/learning lanes, protected completion holds and finite time/work/token/call/dollar caps. No automatic refill, model switch or promise to close a knowledge gap.
- Time renewal applies only to unchanged unstarted checked preparations with exact confirmation. It retains the same allowance/caps/usage, journals old/new expiry and starts no work. Reserve local completion before execution and reconcile accepted receipts before deadline disposition.
- Preserve immutable source bytes/spans, exact disclosure, typed historical intervals, unknown/disputed support and bounded push queues. Append credentials cannot read models or grant policy/spending/publication authority. No implicit pull connector is introduced.
- Named deletion fences access/publication before durable cleanup. Preserve uncertain accounting, independent models and external backups. Logical deletion is not secure media erasure.
- Current owned schema is 15. Preserve transactional supported migrations and paired restore. Foreign/future stores fail closed. Restore disables remote authority and revokes operational credentials.

## Runtime and verification

- The supported container target is Linux ARM64, non-root/read-only, with bounded compute, separate networks/credentials and gateway-only provider access. Keep application seccomp, host publication and health checks intact.
- Preserve actual runtime data and secrets during ordinary builds/updates. Use dedicated `awm-adm-check-*` projects, separate ports/hostnames and disposable models for runtime/deletion checks. Never use a user's installation as a fixture.
- Automated checks use recorded/simulated providers only. Any live call, including a connection test, interpretation or explanation, needs explicit user scope/disclosure and budgets. Configuration and administrator setup make no provider call.
- Run `make check`, `make isolate` and appropriate runtime checks for substantive changes. Set `AWM_ADM_LEAN` to an absolute Lean 4.19.0 path for host proof checks; skipped real-kernel tests are not proof evidence. Docker includes its pinned compiler.
- Run npm in `console/` or through the Makefile. Keep private data, `.local`, credentials, caches and personal test reports ignored. Source exports use `scripts/export_release.py`; publication checks must exclude development history and validate local documentation links.
- Retain third-party notices and provenance. Write current product/contributor documentation as standalone descriptions; archive development plans and personal trial records outside this repository. Do not commit or publish without the user's instruction.
