# Testing and assurance

The test suite checks the documented finite engine and local service. It uses independent expected outcomes, synthetic fixtures and recorded/simulated providers. No automatic test needs an account key or makes a paid provider call.

Evidence-recall tests distinguish storage from intended question support. Recorded Teach→Ask fixtures preserve event/inspection/report clocks and supplied-calculation provenance; independent measurements, inventory and forecasts cover collection limits, context-bound cursors, held evidence and snapshot reads. These are offline integration checks, not live-provider reliability measurements.

## Reproduce

Use the commands in [Contributing](../CONTRIBUTING.md): `make bootstrap`, `make check`, `make build` and `make isolate`. Set `AWM_ADM_LEAN` to an absolute Lean 4.19.0 executable for real host kernel checks. The Docker test target includes that compiler and runs non-editably without a parent project. Run it with network disabled, a read-only root, dropped capabilities and bounded resources as shown there.

`make isolate` builds a public source export, installs it into a new environment with Python isolated mode, tests and builds offline using warmed dependency caches. `scripts/check_boundaries.py` rejects parent imports and source symlinks. `scripts/check_public_release.py` checks public-file exclusions and local documentation links. These checks supplement actual installation, not a claim of a sandbox against deliberately obfuscated code.

## Coverage

| Boundary | Meaningful checks |
| --- | --- |
| Finite semantics | Independent fixture truth tables; typed expression/algebra checking; planning witnesses, bounds and action selection |
| Admission | Owner requirements, receipt order, forward/backward conflicts, dependent declarations and publication fences |
| Proofs and snapshots | Real Lean when configured, exhaustive correspondence, exact result contexts, corrupted/traversing archives and independent imports |
| Durable requests | Idempotency, cancellation, atomic request/result/events, interrupted attempts, immutable histories and budgets |
| Learning and dispatch | Private construction, bounded diagnostics, at-most-once grants, unknown holds, finite task stopping and restart |
| Chat and teaching | Direct inputs, bounded automatic context, invalid preparation, source-field contracts, automatic admission, cancellation and local outcomes versus narration |
| Sources and lifecycle | Exact spans, corrections/held support, unknown dates, bounded queues, deletion races and independent copies |
| Temporal evidence | Mixed instant/occurrence/validity/period meanings, attributed reports, source clocks, precise units, legacy coexistence, conflict identity, paginated local queries and snapshot feature fencing |
| Access and operations | Local peer/origin boundaries, private channel isolation, schema compatibility, paired recovery, conservative accounting and egress restrictions |
| Public API | Unified `/api/v1`, separate interpretation/chat histories across restart, retired routes without side effects and generated OpenAPI drift |
| Codex project workflow | Project-required readiness, stable binding/reuse, durable Ask/Teach recovery, stale-revision refusal, explicit mode changes, bounded knowledge reads and native MCP stdio |
| Console and packaging | Latest-100 Ask/Teach windows, explicit older batches, stable cursors during arrivals, failed-page retry, preserved prepend anchor and off-screen reply context, draft/attachment retention, scroll handoff and auto-follow, readable outcomes/charts/tables, types/build, import independence, exports and documentation boundaries |

`contracts/workflows/` contains versioned specification oracles and authored equipment/access fixtures, including historical accounting profiles. `scripts/verify_workflow_contracts.py` validates them; its abstract state/price models are not proofs that the runtime refines those models or current spending prerequisites. Current direct-interaction cases are in `contracts/interaction-corpus.json`. Integration tests separately exercise actual SQLite, workers and APIs.

Conversational regressions cover linked owner-context disclosure, changed scenario inputs, retained unresolved assumptions, missing/ambiguous inputs, range rejection, model changes during interpretation, exact result bindings and separate narration. Presentation checks keep computed values visible, retain complex/uncertain outcomes and preserve accepted teaching objectives. These recorded-provider tests verify the integration contract; they do not measure a live model's ability to resolve references or phrase explanations correctly.

`tests/test_temporal_contracts.py`, `test_temporal_evidence.py`, `test_temporal_teaching.py` and `test_temporal_recovery.py` check the service temporal adapter independently of the finite kernel. Synthetic oracles distinguish exact observations, uncertain occurrence windows, validity coverage and whole-period values. Fault injection after revision writes, support updates and receipt/event writes verifies transaction rollback and stopped-work recovery with no partial knowledge. Compatibility checks retain legacy bytes and reject stripped feature envelopes, forged evidence and unsupported temporal rewrites. These are implementation checks, not external-source truth or a formal verification of the Python adapter.

`tests/test_preparation_readiness.py` distinguishes information gaps from capability limits using unrelated synthetic subjects and unchanged model-neutral guidance. It checks structural routing without prose matching, invalid assessments, exact input references, old-profile decoding, ready-plan schema/validation parity, durable clarification after restart, retained attachments, idempotency and the absence of premature learning or automatic retries. These tests do not certify provider semantic classification.

Correction regressions in `tests/test_teaching_revision.py` cover transitive dependent preservation, atomic overlapping corrections, provider tampering, invalid retained assertions and honest partial outcomes. `tests/test_revision_vocabulary.py` checks revision-compatible inherited metadata without weakening new metadata validation or silently retargeting ambiguous aliases. These service-layer checks leave the finite engine's admission rules unchanged.

`tests/test_publication_changes.py` checks before/after interface changes, added/removed declarations, bounded and historical missing reports, source values/time scopes and support changes, and actual source-teaching delivery. Revision regressions require unchanged dependent definition digests with new artifact bindings and exact accepted revisions. Reporting never changes the candidate or substitutes narration for a checked result.

A bounded native Codex walkthrough separately exercised creation, teaching, supported Ask results, backward rejection, forward revision with a preserved dependent definition, explicit backward return, fresh-chat recall and the no-project reminder. The initial failed forward revision and later successful checks remain distinct evidence. This synthetic finite scenario is not a measurement of arbitrary project knowledge or general acquisition reliability.

## Docker rehearsals

The release rehearsal runs synthetic equipment scenarios in a fresh exported package with its own credentials, named volumes and loopback port. It checks single-connection activation, automatic mixed teaching, supported/unknown Ask outcomes, unified history, snapshots, restart and gateway-independent local serving. It makes no live provider calls. Use an unused `awm-adm-check-release-*` project name and port; the commands below use port 8089. Docker Compose must support the `!override` tag.

From a contributor checkout, export to a new absolute path outside its source directories, then enter that package:

```sh
python3 scripts/export_release.py /absolute/new/path/awm-adm-rehearsal
cd /absolute/new/path/awm-adm-rehearsal
python3 scripts/export_release.py . --verify
python3 scripts/setup_runtime.py
```

Prepare the app configuration and Compose override. Both the application listener and host publication use the test port; changing only the port mapping would fail the application's Host check. The override retains the standard network, security and storage configuration.

```sh
python3 - <<'PY'
from pathlib import Path

config = Path("deploy/config.toml").read_text()
assert config.count("\nport = 9527\n") == 1
with Path(".local/rehearsal.toml").open("x") as stream:
    stream.write(config.replace("\nport = 9527\n", "\nport = 8089\n", 1))
with Path(".local/rehearsal.compose.yaml").open("x") as stream:
    stream.write('''services:
  app:
    ports: !override ["127.0.0.1:8089:8089"]
    volumes:
      - ./.local/rehearsal.toml:/opt/awm-adm/config.toml:ro
  provider-gateway:
    networks: !override [internal]
    command: [python, /verification/scripts/runtime_fixture_gateway.py, gateway]
    volumes:
      - ./scripts:/verification/scripts:ro
      - ./examples:/verification/examples:ro
''')
PY
docker compose -p awm-adm-check-release-local -f compose.yaml -f .local/rehearsal.compose.yaml build
docker compose -p awm-adm-check-release-local -f compose.yaml -f .local/rehearsal.compose.yaml up -d --no-build --wait --wait-timeout 60
/path/to/contributor/.venv/bin/python scripts/verify_release_runtime.py --package . --project awm-adm-check-release-local --override .local/rehearsal.compose.yaml --port 8089 --output .local/rehearsal-report
```

The verifier requires the contributor Python environment (for credential sealing), an empty test installation and the fixture gateway above. The console opens directly without an account for optional browser inspection. The synthetic provider key is `synthetic-test-secret`; the gateway has no egress network. These fixtures are not production credentials. The verifier can stop/restart its services. Read `.local/rehearsal-report/report.json`; retain the report privately. After inspection, remove **only this disposable test stack and its volumes**:

```sh
docker compose -p awm-adm-check-release-local -f compose.yaml -f .local/rehearsal.compose.yaml down -v
```

The source manifest describes the clean export before runtime setup. Adding ignored `.local` files intentionally makes the working test directory differ from that clean manifest; keep a separate untouched export for distribution verification.

Other `scripts/verify_*_runtime.py` helpers require their own documented project prefixes. The operations helper accepts explicit overrides and test ports. `verify_runtime.py` and `verify_api_runtime.py` instead test the default 9527 mapping on a dedicated Docker host where that port is unused; they are not suitable for running beside a normal 9527 installation. Inspect each helper's `--help` and arguments before use. Never use normal installation credentials or volumes as test fixtures.

## Dependency inventory

With locked contributor dependencies installed, regenerate the portable package/license inventory:

```sh
.venv/bin/python scripts/dependency_inventory.py > docs/dependency-inventory.json
```

The inventory covers the service, independently installed Codex plugin and console. It retains all three lock hashes, dependency versions, artifact origins, declared licenses and container pins. It excludes host identity, tool versions and installation flags. Python license metadata comes from the exact locked distributions in each package’s own environment when available; Node metadata comes from the lock or the matching package. Missing license metadata is explicit. This is package provenance, not a vulnerability or redistribution clearance.

## Interpretation of results

A passing finite fixture establishes its expected behavior under the checked representation and configuration. It does not establish universal learning reliability, semantic correctness of arbitrary natural language, empirical truth or unlimited throughput. Unconfigured Lean skips do not satisfy a real-kernel gate. The interpreter/translator remain trusted code; lifecycle specification traces are not a formal implementation refinement proof.

Keep failed live outcomes and uncertainty honest. New live trials require explicit disclosure, model/connection and budgets, and are distinct from automatic regression. No model comparison is needed to establish model-neutral guidance.

Temporal regressions in `tests/test_temporal_interaction.py` and source-guidance tests cover service defaults, explicit zones, DST, captured disclosure, strict source validation, representable-date boundaries, period coverage, disputes, changing values, snapshots and unknown follow-ups. Connection regressions distinguish queued work from actual calls and expire unclaimed tests without retrying uncertain dispatches. Authored provider replies do not measure live interpretation accuracy.

Temporal guidance regressions check model-independent ordered wire descriptions, rejection without coercion of malformed identifiers and scopes, sanitized durable diagnostics with no automatic retry, and retained/current preparation decoders through complete recorded Teach/Ask flows. These are offline checks; they do not establish provider reliability.

Knowledge-intent regressions cover both extraction formats with authored assertion, quotation, negation and hypothetical replies. They check actual dispatched guidance/schema, exact original content, held non-assertions, candidate-only extraction, unchanged revision/mode and no automatic repeat. Preparation stays model-neutral, and retained preparation formats remain decodable. These recorded responses do not measure live classification accuracy or certify model-premise adoption; see [knowledge intent](KNOWLEDGE_INTENT.md).

## Preparation transport assurance

Offline regressions cover the common call policy, queue/execution separation, aggregate exhaustion, simulated slow responses, DNS/TLS/connection/HTTP errors, response-size refusal and gateway child start/exit/output/timeout failures. Diagnostics preserve observed timing without raw exception or credential disclosure. Timeouts, incomplete output and invalid proposals remain distinct; historical uncertainty is not reclassified.

`tests/test_shared_llm_review.py` checks finite feed-envelope overflow through the public API, smaller explicit lifetime budgets, retained lease expiry and result callbacks before/after timeout reconciliation. The three-second delivery window cannot authorize another provider call; late known usage settles without admitting the late payload. Recorded callbacks and controlled clocks exercise these races without paid calls or wall-clock delays.

Retained Ask/Teach exchanges without shared-policy provenance stop before dispatch, keep their submission identity and leave accepted knowledge unchanged. Replaying them does not acquire today's settings or make a provider call.

Connection recovery checks also cover an Enable operation without captured limits: reattach an already-reserved grant with its original bounds, or stop disabled without creating a test. Saved credentials, accounting and replay identity remain intact.

`tests/test_shared_llm_limits.py`, `test_learning_capacity.py` and `test_acquisition_timeout.py` verify shared defaults, aggregate arithmetic, partial overrides, explicit smaller limits, durable idempotent capture, parent accounting, pre-dispatch refusal and separate queue expiry. Known and uncertain accounting remain distinct. Fake clocks exercise deadlines without paid calls.

`tests/test_preparation_field_bounds.py` checks model-neutral schema descriptions against unchanged local validators, character/count boundaries, redacted diagnostics and retained preparation decoding. A concise child objective remains linked to the complete original teaching input used for acquisition; shortening the objective does not truncate the requirements. Recorded failures retain their identity without automatic repair or retry.

Clarified intake regressions exercise combined message/upload extraction, exact Unicode bytes and spans, exclusion of unselected material, source correction holds in current/imported models, refusal to reprocess packets with superseded originals, malformed-span rejection, separate queue/call deadlines, and retained child diagnostics without provider access. The finite algebraic kernel, claim validators and proof checkers remain unchanged by these orchestration paths.

`tests/test_extraction_timeout.py` exercises Teach intake, managed queues and direct source/feed APIs with recorded providers and simulated clocks. It checks shared six-minute defaults, explicit smaller bounds, separate queue allowance, full admission after a slow simulated response, and retained uncertainty without redispatch.

`tests/test_extraction_capacity.py` checks shared output defaults and matching feed/grant/wire reservations with unmodified source validation. Explicit smaller budgets stay bounded. Known failed usage settles, incomplete output publishes nothing, and unknown usage remains reserved. Changed defaults do not alter retained work after restart. These checks do not measure live reliability.

Catalog-capacity and teaching-intent regressions cover cumulative 18+19−1 growth, the 65,536 numeric ceiling and safe overflow counts, sparse registries, bounded extraction selection, exact retained identities and independent snapshot reads. Recorded-provider teaching checks preserve original intent alongside generation provenance, optional caller classifications and unchanged local answers. These tests do not establish large-codebase throughput, natural-language classification reliability or authenticated human agreement.

Settings regressions cover atomic validation, concurrent-edit rejection, identical replay, restart persistence, schema-18 migration and rollback, captured Ask/Teach and connection-test limits, and lower capacity settings preserving accepted facts/snapshots while refusing growth. Console tests verify exact units and invalid drafts. All providers in these checks are simulated.

Recorded-provider reaffirmation regressions cover unchanged definitions in both modes, retained evidence and snapshots, idempotency, cancellation/pause/stale-context fences, mixed partial outcomes and safe shape diagnostics. These checks do not establish live interpretation reliability.

## Trusted container access

`tests/test_trusted_clients.py` checks configuration defaults and rejection, paired Host/socket-peer admission, browser and forwarded-header rejection, body limits, workspace operations and separate private authentication. Rehearse actual Docker transport only on a disposable installation: a configured private-network client must succeed, a different subnet must receive 403, and host loopback must remain usable. The [deployment guide](TRUSTED_CLIENTS.md) supplies the opt-in topology; tests make no provider calls.
