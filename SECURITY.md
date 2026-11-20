# Security boundary

AWM-ADM 0.4.0 supports a trusted local workspace on a Linux ARM64 Docker host. The console binds to `127.0.0.1:9527`. Internet exposure, reverse proxies, shared-host multi-tenancy and remote administrator access require a separate deployment/authentication design and are not supported by this release.

The application stores accepted models and account data. The gateway owns encrypted provider credentials and outbound provider access. The supported Compose stack uses non-root, read-only containers, separate networks, role credentials, bounded processes and an application seccomp profile. The host/operator and local access remain trusted; there is no user authentication. Same-origin browser checks and loopback deployment prevent unrelated websites or direct off-host callers from using the service. A deliberate trusted local relay is outside this boundary.

## Protect local material

- Keep `.local/`, service tokens, the gateway encryption key, credentials, cookies, databases and paired backups private. Provider keys belong in the secure Connections form, not chat or committed files.
- The console and public APIs are login-free. Any trusted local client can manage the service; the plugin intentionally exposes only its needed operations. Do not publish this listener remotely.
- Preserve gateway encryption material separately from paired backups. A snapshot of a model is not a service backup.
- Source text and provider output are untrusted. They cannot configure the provider, install owner requirements or bypass local admission.
- Unknown provider usage remains reserved. Cleanup, restart or restoring an old backup cannot establish that an external charge did not occur.

## Reporting an issue

Do not post credentials, private source material, databases or exploitable details in public issues. If the hosting repository provides private vulnerability reporting, use it; otherwise contact the maintainer privately before sharing sensitive details. This source distribution does not declare a public security email or guarantee a response time.

Report the version, affected component, minimal synthetic reproduction and expected/actual behavior. Remove secrets and account identifiers from logs. Never test a suspected issue against another user's data or provider account.

Supported security reports apply to the current 0.4.0 release. The bounded test suite is not an exhaustive security audit or certification.
