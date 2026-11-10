# Testing and assurance

The test suite checks the documented finite engine and local service. It uses independent expected outcomes, synthetic accounts and recorded/simulated providers. No automatic test needs an account key or makes a paid provider call.

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
| Learning and spending | Private construction, bounded diagnostics, at-most-once grants, unknown holds, separate lanes, cap/deadline stopping and restart |
| Chat and teaching | Scoped disclosure, exact decisions, invalid preparation, source-field contracts, local outcomes versus narration, time renewal and late source completion |
| Sources and lifecycle | Exact spans, corrections/held support, unknown dates, bounded queues, deletion races and independent copies |
| Access and operations | Password/CSRF/session boundaries, role separation, schema compatibility, paired recovery, conservative accounting and egress restrictions |
| Public API | Unified `/api/v1`, separate interpretation/chat histories across restart, retired routes without side effects and generated OpenAPI drift |
| Console and packaging | Strict JSON/query forms, draft retention, readiness, types/build, import independence, exports and documentation boundaries |

`contracts/workflows/` contains executable specification oracles and authored equipment/access fixtures. `scripts/verify_workflow_contracts.py` validates them; its abstract state/price models are not proofs that the runtime refines those models. Integration tests separately exercise actual SQLite, workers and APIs.

## Docker rehearsals

The release rehearsal runs recorded local scenarios in a fresh exported package with its own credentials, named volumes and loopback port. It checks acquisition, interpretation, source history/conflicts/corrections, snapshots and gateway-independent local serving. It makes no live provider calls. Use an unused `awm-adm-check-release-*` project name and port; the commands below use port 8089. Docker Compose must support the `!override` tag.

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
assert config.count("\nport = 8080\n") == 1
with Path(".local/rehearsal.toml").open("x") as stream:
    stream.write(config.replace("\nport = 8080\n", "\nport = 8089\n", 1))
with Path(".local/rehearsal.compose.yaml").open("x") as stream:
    stream.write('''services:
  app:
    ports: !override ["127.0.0.1:8089:8089"]
    volumes:
      - ./.local/rehearsal.toml:/opt/awm-adm/config.toml:ro
''')
PY
docker compose -p awm-adm-check-release-local -f compose.yaml -f .local/rehearsal.compose.yaml build
docker compose -p awm-adm-check-release-local -f compose.yaml -f .local/rehearsal.compose.yaml up -d --no-build --wait --wait-timeout 60
python3 scripts/verify_release_runtime.py --package . --project awm-adm-check-release-local --override .local/rehearsal.compose.yaml --port 8089 --output .local/rehearsal-report
```

The verifier requires an empty test installation and can stop/restart its services. Read `.local/rehearsal-report/report.json`; retain the report privately. After inspection, remove **only this disposable test stack and its volumes**:

```sh
docker compose -p awm-adm-check-release-local -f compose.yaml -f .local/rehearsal.compose.yaml down -v
```

The source manifest describes the clean export before runtime setup. Adding ignored `.local` files intentionally makes the working test directory differ from that clean manifest; keep a separate untouched export for distribution verification.

Other `scripts/verify_*_runtime.py` helpers require their own documented project prefixes. Learning, language, sources, feeds and operations helpers accept explicit overrides and test ports. `verify_runtime.py` and `verify_api_runtime.py` instead test the default 8080 mapping on a dedicated Docker host where that port is unused; they are not suitable for running beside a normal 8080 installation. Inspect each helper's `--help` and arguments before use. Never use normal installation credentials or volumes as test fixtures.

## Dependency inventory

With locked contributor dependencies installed, regenerate the portable package/license inventory:

```sh
.venv/bin/python scripts/dependency_inventory.py > docs/dependency-inventory.json
```

The inventory retains lock hashes, dependency versions, artifact origins, declared licenses and container pins. It excludes host identity, tool versions and installation flags. Python license metadata comes from the exact locked distributions when available; Node metadata comes from the lock or the matching package. Missing license metadata is explicit. This is package provenance, not a vulnerability or redistribution clearance.

## Interpretation of results

A passing finite fixture establishes its expected behavior under the checked representation and configuration. It does not establish universal learning reliability, semantic correctness of arbitrary natural language, empirical truth or unlimited throughput. Unconfigured Lean skips do not satisfy a real-kernel gate. The interpreter/translator remain trusted code; lifecycle specification traces are not a formal implementation refinement proof.

Keep failed live outcomes and uncertainty honest. New live trials require explicit disclosure, model/connection and budgets, and are distinct from automatic regression. No model comparison is needed to establish model-neutral guidance.
