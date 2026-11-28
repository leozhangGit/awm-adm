# Install and run with Docker

The supported target is **Linux ARM64**, including Linux containers on Apple Silicon Docker Desktop. AMD64, Windows-native containers, public internet hosting and shared multi-user installations are not verified for 0.4.0.

## Requirements

Install Docker Engine/Desktop with Compose v2 and Python 3.10+ for the standard-library setup helpers. Application dependencies, Node and Lean are built inside Docker; host development requires Python 3.13 and Node 22 as described in [Contributing](../CONTRIBUTING.md).

Allow several GiB of working disk space beyond the installed images. The application container is limited to 3 GiB RAM/two CPUs; worker and gateway each have an additional 512 MiB/one CPU ceiling. Dependency/test builds may need more resources. Initial downloads require network access; supported local model execution does not require a provider account.

## Build and start

From the repository directory:

```sh
python3 scripts/setup_runtime.py
docker compose build
docker compose up -d --no-build --wait --wait-timeout 60
docker compose ps
```

Setup creates separate owner, worker and gateway tokens plus a gateway encryption key under ignored `.local/secrets/`. Existing secrets are retained. The Docker build uses pinned bases, locked Python/Node dependencies and a checksum-verified Lean 4.19.0 distribution. No parent source directory or private release archive is required.

The standard project is named `awm-adm`. Its app, learning worker and provider gateway must become healthy. The console is at **http://127.0.0.1:9527/**. Only the public application listener is published; private control and component listeners stay on the internal network.

## Open the workspace

Open **http://127.0.0.1:9527/** directly. There is no account setup or login. In Connections, enter the provider/model/key privately and click Enable when ready to use Ask/Teach. The same local API requires no service key. See [local access](LOCAL_ACCESS.md).

## Configure models and providers

In **Connections**, select the provider, enter its model identifier and API key, then click **Enable**. This sends one bounded connection test; success enables remote capabilities. Failure leaves the connection disabled with a reason. **Disable** retains the configuration and private key for later reuse.

Create an empty model or import a snapshot in **Domain models**. Ask and Teach are ready to use when the connection is enabled; there is no interaction setup, pricing installation or allowance. Supported structured requests remain available through the API without a provider. See [Connection](CONNECTION.md) and [Console](CONSOLE.md).

## Configuration and data

`deploy/config.toml` is the container configuration. Its loopback publication, private networking, process/resource limits and role-secret mounts form the supported deployment boundary. `config/default.toml` describes host/library defaults. Configuration is strict: unknown fields, invalid limits and foreign stores are rejected.

The console's installation **Settings** page persists shared provider-call limits and the temporal predicate cap without a restart. Saved values override the corresponding startup defaults; other runtime settings remain in the configuration file. See [Settings](SETTINGS.md).

For an integration running in a separate Docker container, configure the opt-in [trusted client network](TRUSTED_CLIENTS.md). The supplied Compose override preserves loopback console publication and joins only the app to a dedicated private bridge. The explicit Host/source-network policy requires an application restart; it is not enabled by Console Settings.

Configuration files use `awm-adm-config/3` with one `[llm.call]` policy. If you maintain a custom `awm-adm-config/2` file, convert it offline before starting the new service with `.venv/bin/python scripts/convert_llm_config.py old.toml new.toml`. Review the mapping, then run `.venv/bin/python -m awm_adm check-config new.toml`. Custom old call limits require explicit shared-limit choices; see [configuration conversion](LIMITS.md#other-independent-bounds). Keep the original file with the paired rollback backup. Conversion does not rewrite retained model or provider records.

The named `adm-data` volume stores models, conversations, requests, accounting and historical actor records. `gateway-data` stores provider state and encrypted credentials. `.local/secrets/gateway-master-key` is required to recover encrypted credentials. Keep that key private and back it up separately. The provider-secret mount is for explicit operator configuration; the normal secure Connections form uses managed credentials.

## Stop and restart

```sh
docker compose stop
docker compose up -d --no-build --wait --wait-timeout 60
```

Named volumes and existing secrets are reused. `docker compose down` removes containers/networks while preserving named volumes; **adding `-v` deletes model/history/provider data**. Do not use volume deletion as a repair or ordinary shutdown step.

For updates, take a consistent paired backup, build the new images, and recreate services with `docker compose up -d --no-build --wait`. Recheck health and retained state. Existing schema migrations remain transactional; downgrade to incompatible code requires a compatible backup rather than opening newer stores. [Operations](OPERATIONS.md) contains backup and restore commands.

System timezone: Docker setup captures the host default automatically; native execution uses the service system default. Explicit user/source timezones take precedence. See [temporal interpretation](TEMPORAL_INTERPRETATION.md) for date precision and replay semantics.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Build fails for the architecture | 0.4.0 verifies Linux ARM64; use an ARM64 Docker environment. |
| Build/start reports no space | Check both host and Docker VM free space. Remove only identified disposable build artifacts; preserve volumes and recovery keys. |
| Port 9527 is occupied | Stop the conflicting service or configure an isolated project/port consistently. |
| Remote calls unavailable | Check the single connection state and its reported failure, plus gateway health. |
| Known local query works but chat is unavailable | Structured local execution is independent of the provider used for chat interpretation and explanation. |
| A provider outcome is unknown | Inspect retained diagnostics/reservations; do not assume a free call or automatic safe retry. |

Use `docker compose ps` and `docker compose logs --tail 100` for service diagnostics. Avoid sharing logs or private stores without checking for sensitive content. For a separate rehearsal use a distinct project, hostname/port and empty volumes; see [Contributing](../CONTRIBUTING.md).
