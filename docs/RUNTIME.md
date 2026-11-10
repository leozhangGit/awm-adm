# Local runtime and Docker operation

The runtime packages the finite engine as a single-host runtime with a registry, independent persistent ADM stores, supervised local computations and a browser owner console. The [authenticated application API](API.md) exposes persistent requests, events, owner settings and bounded model operations. The private operator interface remains available. The [console](CONSOLE.md) manages models, structured requests, inspection and snapshots; the [learning service](LEARNING.md) manages bounded acquisition.

## Start and inspect

The supported image platform is **Linux ARM64**, including an ARM64 Docker Desktop host. Docker Engine with Compose and Python 3 are needed on the host for setup. Python application dependencies, Node and Lean run inside the build/runtime images. AMD64 is not verified for this release.

From the `awm-adm` directory:

```sh
make runtime-setup
docker compose up -d --build --wait --wait-timeout 60
docker compose ps
```

The service uses [administrator setup and email/password login](ADMINISTRATOR.md). Use a separate project, hostname/port and empty volumes for rehearsals. The first build downloads the pinned images, locked dependencies and the hash-checked Lean distribution. Running the built service needs no provider account. Setup creates a gateway encryption master key and three distinct local service tokens under `.local/secrets`, preserves existing tokens and never prints their contents. These are runtime authentication tokens, not provider keys. The containing host directory is owner-only; individual mounted token files are readable by the non-root container user.

`make up`, `make status` and `make stop` provide the corresponding setup/start, inspection and stop commands. Only TCP port 8080 is published, bound to `127.0.0.1`. The internal control listener is not published.

```sh
docker compose run --rm --no-deps -T operator create "My first ADM"
docker compose run --rm --no-deps -T operator list
docker compose run --rm --no-deps -T operator info INSTANCE_UUID
docker compose run --rm --no-deps -T operator capabilities INSTANCE_UUID
```

An empty instance has no domain declarations. To create an independent instance from a supported model snapshot:

```sh
cat model.adm | docker compose run --rm --no-deps -T operator create "Imported ADM" --snapshot -
```

Restore rechecks artifacts, owner requirements, evidence closure and typed state locally. The receiving instance has a fresh UUID; source identities remain provenance. The mode defaults to backward; `--mode forward` selects the initial forward policy. Persistent mode/policy mutation is available through the owner API. Persistent candidate publication uses the learning ordered receiver coordinator.

Run a supported structured query by supplying a JSON object with `query` and optional lower `limits`:

```sh
printf '%s\n' '{"query":{"op":"capabilities"}}' |
  docker compose run --rm --no-deps -T operator query INSTANCE_UUID
docker compose run --rm --no-deps -T operator run INSTANCE_UUID RUN_UUID
```

These operator calls are synchronous and authenticated on a private runtime protocol. They have no public request idempotency, learning trigger, event stream or automatic retry. A lost response does not imply an operation failed to commit. Inspect existing instances before retrying creation. The [public API](API.md) supplies durable request identities and recovery workflows. `explain` through the engine dispatcher needs a history adapter; use `operator run` to inspect the runtime run record.

The HTTP ingress limit is 2 MiB, including a snapshot's base64 transport envelope. Larger core-library snapshots are unsupported by the current API/console transport; the service never silently truncates them. Streaming archives are a separate extension.

## Runtime and authority

| Component | Storage and network | Service behavior |
| --- | --- | --- |
| App | Owns `adm-data`; internal plus ingress networks; one loopback-published console/API port; outbound connections blocked by seccomp | Owns the registry and per-ADM stores; authenticates operator/component calls; supervises local compute children. |
| Local compute child | Receives immutable model/query data; no store handle or credential environment | Rechecks the model and owner policy, executes locally and returns a bound result. |
| Learning worker | No database volume; internal network only; worker token | Claims one bounded acquisition per job; contacts the private gateway with a lease. No key or publication authority. |
| Provider gateway | Own encrypted credentials/dispatch ledger in `gateway-data`; internal and egress networks; component authentication and gateway-only master key | Authorizes against app reservations, records before dispatch, and delivers bounded final output. Remote calls require explicit owner enablement and budget. |

The `operations` tools-profile command runs offline backup/restore with both data volumes, no network and no secret mounts; it requires stopped storage owners. The `operator` tools profile creates a short-lived client on the private network with only the owner token and no database volume. It is not a fourth long-running service.

The app has separate public and private listeners. Public routes expose health, minimal system capabilities, built console assets and the authenticated application API. Private routes require distinct owner, worker or gateway credentials. Component credentials cannot create instances or submit owner computations. The worker/gateway have no access to the app's database volume. A local Docker administrator remains inside the host trust boundary.

The internal network denies ordinary external TCP access for the worker and operator client. The app also joins an ingress bridge so Docker can publish the loopback port. Its [seccomp profile](../deploy/app-seccomp.json), derived from the pinned Docker baseline, allows only Unix/TCP stream sockets, denies `connect`, addressed datagram sends and alternative io_uring/socketcall paths, and permits buffered replies on accepted streams. Datagram and raw socket creation are denied. This policy is inherited by compute children. Only the gateway joins the provider egress network. Removing the app policy is not a supported deployment. The gateway is not a general proxy. Its adapters use fixed official OpenAI/Anthropic destinations; credentials and grants follow [LEARNING.md](LEARNING.md). Network membership does not grant learning or publication authority.

## Persistence and recovery

[`runtime/storage.py`](../src/awm_adm/runtime/storage.py) owns a small registry and one SQLite database per generated ADM UUID. Client-supplied names never become filesystem paths. A directory marker, database application ID and schema version distinguish these stores from foreign databases. AWM-ADM refuses foreign stores and future schema versions. Owned database schemas 1–14 migrate transactionally to schema 15, including the registry-owned priced allowance ledger and per-ADM Conversation records, immutable Ask presentations, retained teaching specifications and idempotent execution commands, immutable uploads, append receipts, source-notice resolutions and registry deletion reconciliation. See [priced allowances](PRICED_ALLOWANCES.md) for accounting, scheduling and legacy-uncertainty boundaries. Administrator/session migration uses a registry upgrade journal; service dispatch/publication cannot start before all stores reconcile. Request attempts retain their revision pins; learning episodes, receipt order, connection versions and grant accounting use owned tables. Interpretation, vocabulary and bounded conversation history use separate per-ADM tables.

An exclusive process lock admits one storage owner. SQLite uses WAL, full synchronous commits and short write transactions. Computation and proof checking happen outside these transactions. This is local-volume storage, not a network filesystem or multi-app-replica design.

Creation first commits a registry intent, then commits the checked instance, then completes the registry intent. Cross-database writes are not described as atomic. Startup completes an intent with a committed instance, or marks a missing/uninitialized one failed. A failure after the per-instance commit leaves the intent recoverable. Corrupt or missing established stores prevent startup instead of silently creating replacements.

The initial accepted snapshot, exact policy/support identities, mode and instance identity survive restart. Each operator computation records an attempt token, app generation, expiry, pinned query/context and terminal result. The parent checks the returned semantic binding before publication. Expired, reclaimed or prior-generation attempts cannot publish. Startup marks interrupted local runs explicitly; it does not invent results or automatically repeat work. Application requests support deliberate local retry with a fresh attempt.

The runtime persists model revisions, immutable origins, local attempts, learning episodes and ordered candidate decisions. Registry, gateway and ADM transactions reconcile conservatively; unfinished episodes stop on app restart, uncertain calls retain reservations and are never automatically repeated. Snapshot import is model cloning; it is not an operational backup or migration of foreign databases.

## Resource limits and readiness

[`deploy/config.toml`](../deploy/config.toml) uses the default finite configuration with a container-local data path. The runtime enforces instance count, retained run count, ingress bytes, configured request caps, global compute concurrency, SQLite page caps and conservative installation-space checks. Failed creation records count toward the instance limit until explicitly deleted. Deleting/deleted identities do not consume live-model capacity; content-free deletion tombstones have a separate 10,000-operation cap. There is no automatic history deletion. Learning also enforces episode and aggregate provider quotas, bounded private drafts, separate background checking and at-most-once dispatch. Sources and feeds enforce bounded source queues and feed lifetime allowances. Owner event pruning and the retention preview are defined in [OPERATIONS.md](OPERATIONS.md); automatic deletion remains disabled.

Each compute child uses the request's work/time limits, including cold snapshot admission and conformance checks. Exhaustion is inconclusive and creates no learning gap. The supervisor adds a bounded process-start/termination allowance and kills the whole process group on timeout or shutdown. Linux children also have CPU, file-size, descriptor and **2 GiB virtual-address-space** limits; the app container has a **3 GiB aggregate memory cap**, two CPUs and a PID cap. Virtual address space and resident memory are different measures. The pinned Lean runtime cannot start a small proof under a 1 GiB address-space cap.

The root filesystem is read-only; data uses named volumes and scratch work uses bounded tmpfs. All services run as UID/GID 10001 with capabilities dropped and privilege escalation disabled. The app's temporary allowance is 256 MiB; worker/gateway temporary allowances are 64 MiB. File/page/space checks are bounded operating controls, not a proof that arbitrary host disk failures are recoverable. The [operations guide](OPERATIONS.md) defines paired offline recovery, storage/queue diagnostics, retention and the measured bounded workload. This does not establish indefinite unattended operation.

The app container health check reads a bounded-age local heartbeat file written only while both HTTP listeners and storage are ready; it does not open a connection from the restricted app.

`/health/live` reports process liveness. `/health/ready` reports local-serving readiness with separate Lean, worker and gateway availability. Stopped components do not disable supported local computation. A component lease expires after 15 seconds; heartbeat visibility is not a statement that learning is running. Missing or wrong-version Lean is explicit, and a requested Lean proof never downgrades to a finite-only success.

## Stop, restart and diagnose

```sh
docker compose logs --tail 100 app learning-worker provider-gateway
docker compose stop
docker compose up -d --wait --wait-timeout 60
```

`stop` preserves containers and data. `docker compose down` removes the stack's containers and networks but retains named volumes by default. **Adding `--volumes` deletes the persisted ADMs and gateway state.** It is not part of normal stopping or verification. Do not change the Compose project name accidentally: it selects a different set of named volumes.

An occupied ownership lock means another app owns the store. An unreadable/corrupt store is a startup failure, not an empty installation. Inspect the diagnostic, stop the competing process or recover from a separately maintained backup; do not remove database files to bypass checks. Use the [offline operations CLI](OPERATIONS.md) for paired backup and fresh-destination restore. Do not copy only a live SQLite main file while ignoring its WAL.

The [console guide](CONSOLE.md) describes owner login, model-driven forms, historical results, snapshots and sandbox clones. The console distinguishes accepted model state from current reachability and reconnects events without replaying mutations. It does not attest external domain truth. Connections and Learning expose bounded acquisition controls. Sources exposes immutable intake, extraction and reviewed historical projections. Sources also exposes [feeds](FEEDS.md), durable cursors, shared interests and explicit coverage transitions.

## Build provenance and verification

The [Dockerfile](../deploy/Dockerfile) pins official Python, Node and uv image digests. Python and console dependencies use their lock files. [`lean-lock.json`](../deploy/lean-lock.json) pins the official Linux ARM64 4.19.0 archive URL, size and SHA-256; build-time installation verifies them. Its digest was measured from the official HTTPS download; the release API supplied no independent asset digest. No compiler is downloaded while serving, and no macOS toolchain is mounted into Linux.

The [seccomp provenance](../deploy/seccomp-provenance.json) identifies the vendored baseline commit, source/profile hashes and license; the app adds restrictions to that baseline. Runtime verification checks host reachability, effective port mappings, private-route exclusion and complete JavaScript/CSS transfer and actual outbound TCP/datagram/raw-socket denial.

Primary implementation references: [Docker seccomp](https://docs.docker.com/engine/security/seccomp/), [Compose services](https://docs.docker.com/reference/compose-file/services/), [internal networks](https://docs.docker.com/reference/compose-file/networks/), [SQLite WAL](https://www.sqlite.org/wal.html), [uv Docker installation](https://docs.astral.sh/uv/guides/integration/docker/), and the [Lean 4.19.0 release](https://github.com/leanprover/lean4/releases/tag/v4.19.0).

Conversation coordination and its bounded worker/decision lifecycle are described in [Ask/Teach workspace](CONVERSATIONS.md). Clarification does not execute a query; exact Ask and Teach decisions separately authorize local execution and checked admission.
