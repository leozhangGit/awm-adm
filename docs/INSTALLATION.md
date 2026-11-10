# Install and run with Docker

The supported target is **Linux ARM64**, including Linux containers on Apple Silicon Docker Desktop. AMD64, Windows-native containers, public internet hosting and shared multi-user installations are not verified for 0.3.0.

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

The standard project is named `awm-adm`. Its app, learning worker and provider gateway must become healthy. The console is at **http://127.0.0.1:8080/**. Only the public application listener is published; private control and component listeners stay on the internal network.

## Establish the administrator

```sh
python3 scripts/admin_credential.py bootstrap --project awm-adm
```

The helper writes a credential to a mode-0600 file and prints its path. Read it locally and paste the value into **Setup credential**. Choose your email identifier and a password of at least 15 characters, then create the administrator. The credential expires after 15 minutes and can be used once. Remove its file afterward. Run the same helper again if it expires before use.

Subsequent login uses email/password. Email is only a local identifier; no mail is sent. For forgotten passwords, use `python3 scripts/admin_credential.py recovery --project awm-adm` and the **Forgot password?** form. See [Administrator](ADMINISTRATOR.md) for recovery/session behavior.

## Configure models and providers

Create an empty model or import a snapshot in **Domain models**. Local debug can serve supported structured queries without an LLM. **Connections** stores provider credentials through the gateway's encrypted workflow; no committed `.env` key is required.

Remote calls and spending default disabled. For Ask/Teach, select connection purposes, install a supported current price profile, set installation interaction/learning limits, enable remote calls explicitly and authorize the conversation/task allowance. Saving a connection is local; pressing **Test** is a separate paid operation. Models without supported pricing cannot dispatch priced chat. See [Spending](PRICED_ALLOWANCES.md).

## Configuration and data

`deploy/config.toml` is the container configuration. Its loopback publication, private networking, process/resource limits and role-secret mounts form the supported deployment boundary. `config/default.toml` describes host/library defaults. Configuration is strict: unknown fields, invalid limits and foreign stores are rejected.

The named `adm-data` volume stores accounts, models, conversations, requests and accounting. `gateway-data` stores provider state and encrypted credentials. `.local/secrets/gateway-master-key` is required to recover encrypted credentials. Keep that key private and back it up separately. The provider-secret mount is for explicit operator configuration; the normal secure Connections form uses managed credentials.

## Stop and restart

```sh
docker compose stop
docker compose up -d --no-build --wait --wait-timeout 60
```

Named volumes and existing secrets are reused. `docker compose down` removes containers/networks while preserving named volumes; **adding `-v` deletes model/account/provider data**. Do not use volume deletion as a repair or ordinary shutdown step.

For updates, take a consistent paired backup, build the new images, and recreate services with `docker compose up -d --no-build --wait`. Recheck health and retained state. Existing schema migrations remain transactional; downgrade to incompatible code requires a compatible backup rather than opening newer stores. [Operations](OPERATIONS.md) contains backup and restore commands.

## Troubleshooting

| Symptom | Check |
| --- | --- |
| Build fails for the architecture | 0.3.0 verifies Linux ARM64; use an ARM64 Docker environment. |
| Build/start reports no space | Check both host and Docker VM free space. Remove only identified disposable build artifacts; preserve volumes and recovery keys. |
| Port 8080 is occupied | Stop the conflicting service or configure an isolated project/port consistently. |
| Setup credential expires | Issue a new credential and complete setup within its window. |
| Remote calls unavailable | Check connection enablement/purposes, global remote switch, supported price validity, spending configuration and conversation allowance. |
| Known local query works but chat is unavailable | Local execution and provider-funded interaction have separate prerequisites. |
| A provider outcome is unknown | Inspect retained diagnostics/reservations; do not assume a free call or automatic safe retry. |

Use `docker compose ps` and `docker compose logs --tail 100` for service diagnostics. Avoid sharing logs or private stores without checking for sensitive content. For a separate rehearsal use a distinct project, hostname/port and empty volumes; see [Contributing](../CONTRIBUTING.md).
