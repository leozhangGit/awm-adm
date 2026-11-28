# Trusted Docker clients

A native client in another container can use the public API through an explicitly trusted private Docker network. The normal console remains at `http://127.0.0.1:9527/`; no login or API key is added. This deployment option does not change model semantics, Ask/Teach, validation or provider configuration.

Inside a client container, `127.0.0.1` refers to that container. The default service also rejects unconfigured HTTP authorities such as `host.docker.internal:9527`. Use a shared private network and service DNS name instead of overriding headers or bypassing the access checks.

## Access contract

The startup configuration has an optional block:

```toml
[server.trusted_clients]
hosts = ["awm-adm:9527"]
source_networks = ["172.30.95.0/24"]
```

Both lists are empty by default. To opt in, supply both. Every request must match **an exact Host and the actual socket peer's configured source network**. Forwarded headers are not used. Each list permits up to 16 unique entries. Hosts are lowercase DNS names or private IPv4 addresses with the configured application port; wildcards, URLs, loopback authorities and alternate ports are rejected. Networks must be explicit, canonical private IPv4 or ULA IPv6 CIDRs, with no host bits. Use a dedicated small subnet or exact client `/32` or `/128` addresses, not an entire private address range.

The opt-in path accepts native HTTP clients only: requests with `Origin` or any `Sec-Fetch-*` header are rejected, including a matching Origin. It does not provide another browser console origin. Existing localhost browser checks, strict JSON/body limits and private machine authentication remain in force. Access configuration takes effect at startup and requires an application restart; it is not a live Console Settings option.

**Every admitted client has full trusted-workspace access**, including model management and provider configuration. This is network trust, not per-client identity, API scoping or multi-user authentication. Attach only services trusted to operate this installation. Docker operators and host processes remain trusted. Remote internet/LAN publication, forwarding proxies and untrusted tenants require a separate authentication/deployment design.

## Configure a shared private network

Run these steps from the AWM-ADM repository. Choose an unused subnet; the addresses below are an example. Preserve existing named volumes and secrets.

1. Create a dedicated, externally managed bridge network:

   ```sh
   docker network create --driver bridge --internal --subnet 172.30.95.0/24 awm-adm-clients
   docker network inspect awm-adm-clients --format '{{.Driver}} {{.Internal}} {{json .IPAM.Config}}'
   ```

   Confirm `bridge`, `true` and the selected subnet. If the network already exists, inspect it rather than replacing it. An internal network has no external route; clients can retain their own separate networks for their other work.

2. Copy the **complete** container configuration to a private override, then edit its existing `[server.trusted_clients]` table to the values above:

   ```sh
   mkdir -p .local
   cp deploy/config.toml .local/trusted-clients.toml
   ```

   If an operator configuration already exists, preserve its other values instead of overwriting it. Keep the standard container paths and application port. Do not append a duplicate TOML table. Saved provider limits in Console Settings continue to override their startup defaults.

3. Build the images and validate the override without provider calls:

   ```sh
   docker compose build
   docker compose -f compose.yaml -f deploy/compose.trusted-clients.example.yaml run --rm --no-deps --entrypoint python app -m awm_adm check-config /opt/awm-adm/config.toml
   python3 scripts/check_local_deployment.py --file compose.yaml --file deploy/compose.trusted-clients.example.yaml
   ```

4. Start/recreate the application using the same Compose project and volumes:

   ```sh
   docker compose -f compose.yaml -f deploy/compose.trusted-clients.example.yaml up -d --no-build --force-recreate --wait --wait-timeout 60
   ```

   The supplied override attaches **only the app** to the client network and mounts the configuration read-only. Worker/gateway networks, secrets, seccomp and loopback port publication remain unchanged. Keep using both files for subsequent updates. The explicit recreation is needed when only the contents of the mounted configuration changed. Plan a restart around active work. Back up the installation before an ordinary code upgrade as described in [Operations](OPERATIONS.md).

   For a persistent installation, you can instead copy the example to `compose.override.yaml` at the repository root. Ordinary `docker compose` commands load that file automatically. If an override already exists, merge the relevant entries rather than replacing it. The root override and `.local/` configuration are excluded from Git, Docker build contexts and source exports; the reusable example under `deploy/` remains public. Commands with explicit `-f` options must still name the override, and deployment checks must receive both files. To return to the default deployment, remove the private override and recreate the services without removing volumes.

5. Add the external network to the relevant client service's own Compose configuration. Merge this with its existing networks and environment:

   ```yaml
   services:
     agent:
       environment:
         ADM_ORIGIN: http://awm-adm:9527
       networks:
         default: {}
         adm-clients: {}
   networks:
     adm-clients:
       external: true
       name: awm-adm-clients
   ```

   `agent` and `ADM_ORIGIN` illustrate an integration such as A-team; use that integration's actual service/configuration names. The client uses port 9527 inside the network and ordinary HTTP headers. Do not attach it to ADM's internal worker/gateway network, share machine secrets, or change the host publication to `0.0.0.0`.

6. From the client, read `GET /api/v1/system` and `GET /api/v1/adms`. These checks make no provider call. Check provider readiness separately before Ask/Teach. A 403 means the Host/port or actual peer does not match, or browser headers were sent; a connection refusal/DNS error means transport or network attachment is not ready. Private listeners still require their own machine credentials and are not integration APIs.

To revoke this access, clear both lists and recreate the app, or restore the standard Compose configuration and recreate it without the client-network attachment. Do not remove data volumes. Removing a network allowlist prevents subsequent HTTP requests; it does not cancel work already accepted by the service. Use ordinary cancellation/connection controls when that is required.

## Verification

`tests/test_trusted_clients.py` exercises default rejection, paired host/peer checks, browser/forwarded-header rejection, content bounds, configuration round trips and private-channel authentication. Deployment rehearsals must use a disposable `awm-adm-check-*` project, private network and empty data. Verify that a client on the trusted subnet can read/create an empty model, a client on a different subnet receives 403, the localhost console still works, and no provider is dispatched. Never run destructive checks against a user's installation.

Docker documents [service discovery across Compose networks](https://docs.docker.com/compose/how-tos/networking/) and [external/internal network configuration](https://docs.docker.com/reference/compose-file/networks/).
