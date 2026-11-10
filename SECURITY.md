# Security boundary

AWM-ADM 0.3.0 supports one administrator on a local Linux ARM64 Docker host. The console binds to `127.0.0.1:8080`. Internet exposure, reverse proxies, shared-host multi-tenancy and remote administrator access require a separate deployment/authentication design and are not supported by this release.

The application stores accepted models and account data. The gateway owns encrypted provider credentials and outbound provider access. The supported Compose stack uses non-root, read-only containers, separate networks, role credentials, bounded processes and an application seccomp profile. The host/operator remains trusted and can recover the local administrator.

## Protect local material

- Keep `.local/`, service tokens, the gateway encryption key, credentials, cookies, databases and paired backups private. Provider keys belong in the secure Connections form, not chat or committed files.
- Use a unique administrator passphrase. Bootstrap/recovery credentials are short-lived and single-use; remove their files after redemption.
- Preserve gateway encryption material separately from paired backups. A snapshot of a model is not a service backup.
- Source text and provider output are untrusted. They cannot change spending, install owner requirements or bypass local admission.
- Unknown provider usage remains reserved. Cleanup, restart or restoring an old backup cannot establish that an external charge did not occur.

## Reporting an issue

Do not post credentials, private source material, databases or exploitable details in public issues. If the hosting repository provides private vulnerability reporting, use it; otherwise contact the maintainer privately before sharing sensitive details. This source distribution does not declare a public security email or guarantee a response time.

Report the version, affected component, minimal synthetic reproduction and expected/actual behavior. Remove secrets and account identifiers from logs. Never test a suspected issue against another user's data or provider account.

Supported security reports apply to the current 0.3.0 release. The bounded test suite is not an exhaustive security audit or certification.
