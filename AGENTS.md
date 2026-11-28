# AWM-ADM contributor instructions

Read `README.md`, `CONTRIBUTING.md`, `docs/ARCHITECTURE.md` and the relevant feature contracts before substantive work. This repository is the standalone AWM-ADM 0.4.0 product. It must build and test without a parent workspace or private development-history files.

## Product boundaries

- Keep the finite engine domain agnostic. Each instance starts empty or from a checked snapshot; examples belong to fixtures, never shared acquisition guidance or core rules.
- Separate fallible provider acquisition/interpretation/narration from authoritative local execution. Only complete checked candidates can publish. Provider/source output cannot grant authority or change independent owner requirements.
- Preserve model-neutral guidance and authored provider-schema order; canonical model artifacts keep their existing sorted encoding. Model choice is explicit configuration, not a branch in task meaning or validation.
- Preserve exact request/result/revision/policy/support bindings, action-selection intent and separate witness/shortestness/unreachability claims. Lean kernel checks and exhaustive correspondence remain distinct; never accept caller-provided Lean source or silently downgrade a requested check.
- Forward conflict mode prefers later receiver arrivals; backward mode retains earlier arrivals. Receipt sequence is local and monotonic. Mode changes affect future decisions only; replacement checks dependent conclusions.

## Service, authority and accounting

- Keep the public API under `/api/v1`, with preview history at `interpretation-sessions` and Ask/Teach history at `conversations`. Preserve existing serialized profiles and stored formats independently of URL versioning. Product version is 0.4.0.
- Provide one connection with Enable/Disable. Successful testing enables remote capabilities together; no per-purpose permissions, pricing installation, monetary allowances, spending quotas or financial expiry are prerequisites. Preserve historical accounting without using it to gate new work.
- Ask/Teach use separate visible streams with automatically managed bounded context. Clear local Teach requests authorize checked automatic learning/publication; clarify uncertain meaning or necessary decisions without routine approvals. Ask does not implicitly teach. Provider text never grants authority or changes independent requirements.
- Preserve durable intents across registry/ADM/gateway boundaries, short atomic publication transactions, context/cancellation/deletion fences and at-most-once provider dispatch. Unknown dispatched calls retain their identity and outcome uncertainty and are never automatically repeated.
- Retain finite per-call execution bounds, per-task attempts/no-progress stopping, compute/storage limits, fair scheduling and cancellation as internal operating protections. Human clarification waits do not expire financial authority. Do not silently change models or promise to close a gap.
- Keep advanced model, proof, source, requirements and diagnostic capabilities accessible through appropriate APIs/library interfaces when their console panels are removed. Preserve current reasoning/resource defaults and full local validation; chat context is not the accepted theory. Distinguish automatic checking from actual human review in provenance.
- Preserve immutable source bytes/spans, exact disclosure, typed historical intervals, unknown/disputed support and bounded push queues. Append credentials cannot read models or expand task/policy authority. No implicit pull connector is introduced.
- Named deletion fences access/publication before durable cleanup. Preserve uncertain accounting, independent models and external backups. Logical deletion is not secure media erasure.
- Current owned schema is 19. Preserve transactional supported migrations and paired restore. Foreign/future stores fail closed. Restore disables remote authority and revokes operational credentials.

## Runtime and verification

- The supported container target is Linux ARM64, non-root/read-only, with bounded compute, separate networks/credentials and gateway-only provider access. Keep application seccomp, host publication and health checks intact.
- Native container access is opt-in through paired exact Host/private-peer allowlists. Defaults remain local-only; trusted containers receive full workspace authority. Preserve browser/forwarded-header rejection and separate worker/gateway networks and credentials; see `docs/TRUSTED_CLIENTS.md`.
- Preserve actual runtime data and secrets during ordinary builds/updates. Use dedicated `awm-adm-check-*` projects, separate ports/hostnames and disposable models for runtime/deletion checks. Never use a user's installation as a fixture.
- Automated checks use recorded/simulated providers only. Engineering live trials need explicit user scope/disclosure and a bounded test budget; past trial authority is not reusable. This testing rule does not add product spending settings. In normal product use, clicking Enable explicitly requests its connection test; workspace startup and background reads make no provider call.
- Run `make check`, `make isolate` and appropriate runtime checks for substantive changes. Set `AWM_ADM_LEAN` to an absolute Lean 4.19.0 path for host proof checks; skipped real-kernel tests are not proof evidence. Docker includes its pinned compiler.
- Run npm in `console/` or through the Makefile. Keep private data, `.local`, credentials, caches and personal test reports ignored. Source exports use `scripts/export_release.py`; publication checks must exclude development history and validate local documentation links.
- Retain third-party notices and provenance. Write current product/contributor documentation as standalone descriptions; archive development plans and personal trial records outside this repository. Do not commit or publish without the user's instruction.
