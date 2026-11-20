# Local workspace access

AWM-ADM opens directly at **http://127.0.0.1:9527/**. The console and all retained public APIs require no account setup, password, service API key, cookie or session renewal. The Login page and setup/login/logout/recovery/token-issuance routes are retired. Existing data does not require a replacement account.

## Trust boundary

This is a single trusted local workspace, not a multi-user authorization service. Any process that can reach the supported local interface can use its public operations, including provider configuration and model management. Browser requests must come from the console's own origin; native clients need no credentials. Host/port validation, peer checks, JSON/content limits and cross-origin rejection remain. Another localhost port is a different origin. A non-secret client label does not authenticate Codex or grant privileges.

Host execution listens only on loopback. Docker publishes only `127.0.0.1:9527` and checks the exact supported gateway peer; the deployment preflight verifies Compose publication. This does not detect a deliberate relay created by a trusted local process. Internet/LAN exposure and forwarding proxies are unsupported.

## Provider and internal credentials

The external provider's API key is still entered privately in **Connections**. It is distinct from service access and remains encrypted by the gateway, masked in reads and absent from prompts/snapshots. Enable performs the explicitly requested connection test; opening the console or reading readiness never calls the provider. Disable stops new provider dispatch.

Explicit source-queue producers can still receive bounded, append-only bearer credentials. These authorize a specified queue and never create a workspace session or a human identity. Legacy account tables are retained only for migration/provenance; password and session-authentication code is not part of the running service.

Private operator, worker and gateway channels retain their separate machine credentials and network isolation. They are not user login mechanisms and are not published on the host.

## Persistence and upgrades

Owned application schema 17 adds a persistent workspace identity. It preserves models, requirements, evidence, pending work, provider configuration and historical actor references. Legacy credential records are revoked; remaining account metadata is historical and does not gate access. New operations use an internal workspace actor, not a claimed authenticated human. Automatic checked learning is not individual human review.

Back up both stores before an upgrade. Schema-16 and other supported older backups remain readable; newer stores fail closed in older code. Restoring a backup disables provider dispatch and preserves uncertain accounting. Use the console directly after restoration; no password recovery is required. See [Operations](OPERATIONS.md).

## Codex plugin

The bundled plugin exposes only the operations needed for its project workflow: Create/bind, Ask, Teach, relevant progress/results and explicitly directed conflict-mode changes. It does not expose full model management or a generic API-call tool. This integration scope is separate from the service's broader local API capabilities.
