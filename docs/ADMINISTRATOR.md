# Local administrator access

AWM-ADM uses one local administrator account with password login, password change and operator-assisted recovery. Administrator setup and account operations make no provider call.

## Set up an installation

The console creates one local administrator. Email is an ASCII, case-insensitive sign-in identifier, trimmed and lowercased; it is not a verified address and no email is sent. There is no public registration, SMTP dependency or external identity service.

During the first 15 minutes after schema-8 migration, the existing installation's owner credential can authorize setup once. This bounded compatibility window also permits the previous AWM-ADM owner/session APIs. Its expiry is persisted and is not extended by restart. Prefer a dedicated setup credential, issued through the separate local operator container:

```sh
python3 scripts/admin_credential.py bootstrap
```

Enter that credential, an email identifier and a new password in **Create your administrator**. Use a unique passphrase of 15–1024 characters. Unicode is normalized to NFC; spaces and paste/password managers are supported. The password is never silently truncated. Setup consumes the credential, revokes previous owner browser sessions, closes the compatibility window and starts an eight-hour administrator session. Issuing a dedicated setup credential also closes the initial owner-token window immediately.

Credential files have mode 0600 and must not already exist. Choose a fresh filename for a later issuance. The helper runs the existing tools-profile operator with the local non-root owner UID, mounts only a private output directory and reports the newly generated file path. Use `--project NAME` and the same Compose configuration as the intended installation. Read that file locally (for example with `cat`) and paste its value into the form. Credential contents are never printed by the helper. The hardened app cannot initiate connections, so do not run this network client with `docker compose exec app`. Remove the credential file after use. It expires after 15 minutes and cannot be redeemed twice. Tokens and passwords belong only in these secure account controls, never in Ask/Teach or provider prompts.

## Sign in and manage the account

Use **Email** and **Password**. The server sets an HttpOnly, SameSite=Strict cookie named `awm_admin_session`, scoped to `/api`, with a fixed eight-hour lifetime. The cookie authorizes both AWM-ADM application routes and AWM-ADM account routes. No sliding lifetime is added by reload. Sessions survive an ordinary application restart.

The console obtains session identity and CSRF state from `/api/v1/auth/me` on reload/focus. It keeps this metadata only in memory; the session credential is never available to JavaScript. Cookies do not isolate ports, so parallel installations should use distinct hostnames. Mutation requests require the session-bound `X-CSRF-Token`. **Sign out** revokes the current session; **Account → Change password** requires the current password and revokes every browser session, including the caller. Sign in again with the new password.

Initial entry and explicit sign-in show a loading screen. Returning focus checks the session in the background without unmounting forms, clearing unsent chat drafts or interrupting file selection. A transient check failure preserves the workspace and offers **Check session again**; an unauthorized session still returns to sign-in. Retaining a draft during a transient failure does not authorize API requests or extend the server session lifetime.

Scoped API clients continue with their original ADM/read/submit permissions after setup, password change or recovery. They gain no administrator authority. Explicit revocation and expiry still apply. Internal worker/gateway tokens remain unchanged. The installation owner token is retained only for the private operator listener after setup; it cannot log in through the public API.

## Recover a password locally

Local control of the application container and its operator credential is the recovery authority. No provider connection is involved:

```sh
python3 scripts/admin_credential.py recovery
```

Select **Forgot password?**, enter the reset credential and choose a new password. Recovery does not require remembering the email, but does not change it. The reset credential expires after ten minutes. A newly issued credential replaces the previous one. Successful redemption consumes all outstanding setup/reset credentials, increments the account generation, revokes all browser sessions and clears authentication throttles. It does not create a new session: use the existing email and new password to sign in. Merely issuing a reset does not change the password or revoke sessions.

Only the private operator listener can issue credentials. Browser sessions, scoped API tokens, worker tokens and gateway tokens cannot use that endpoint. The private listener is not published on the host by the supported Compose configuration.

## Public and private interfaces

| Route | Purpose / authority |
| --- | --- |
| `GET /api/v1/auth/status` | Public setup-required boolean; no account identifier |
| `POST /api/v1/auth/setup` | Single-use setup credential + email + password |
| `POST /api/v1/auth/login` | Email/password; fresh cookie and CSRF state |
| `GET /api/v1/auth/me` | Administrator session; metadata, CSRF and local request limits |
| `POST /api/v1/auth/logout` | Session + CSRF; revoke current session |
| `POST /api/v1/auth/password` | Session + CSRF + current/new passwords; revoke all sessions |
| `POST /api/v1/auth/recover` | Single-use operator-issued reset + new password; no auto-login |
| `POST /internal/v3/auth/bootstrap` or `/recovery` | Private owner/operator credential; one short-lived credential returned once |

The running OpenAPI export specifies inputs. Setup/login profile fields default to their fixed version if omitted. Setup requires a 15-character password and a credential of at least 40 characters. Validation errors never echo supplied secrets. The standard-library example client accepts `--login` for an in-memory administrator session (interactive email/password prompts, logout on exit) or `--token-file` for an explicit scoped API credential. It does not save passwords or cookies.

## Storage, work bounds and security scope

Passwords use the existing maintained `cryptography` dependency's Argon2id PHC implementation: 19,456 KiB memory, two iterations, one lane, a random 16-byte salt and a 32-byte result. These parameters meet the [OWASP password-storage minimum](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html). PHC encoding and verification use the [library's documented APIs](https://cryptography.io/en/stable/hazmat/primitives/key-derivation-functions/#argon2id), rather than a project-authored password algorithm. The 15-character minimum and generic login failure follow [OWASP authentication guidance](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html). This local release does not claim certification or complete NIST conformance; it has no MFA or breached-password service.

Only one password operation can hash/verify at a time in the application process; additional concurrent password work receives `busy`. This prevents an unbounded KDF queue. Persistent admission counters permit five authentication attempts per 15-minute window per operation/peer, and additionally per normalized login identifier. Successful operations clear their associated counters; failures consume them. Setup, recovery and password changes have their own counters. At most 2,048 hashed counter keys are retained; saturation fails closed. The actual transport peer is used, never `X-Forwarded-For`. Password/hash values, plaintext tokens and email identifiers are absent from operational diagnostics. Wrong credentials, expired credentials and nonexistent identifiers receive the same safe authentication failure. This is not a timing-independent cryptographic protocol.

The registry stores the account, bounded ticket/counter tables, a session generation and an installation upgrade journal. The current owned schema is 15; account tables were introduced in schema 8. Each owned database migrates transactionally. Runtime listeners, schedulers and publication are unavailable until all existing stores migrate and reconcile. A failed migration remains marked incomplete and resumes on startup; foreign/future/corrupt stores are refused. Existing model, requirement, evidence, request, grant and gateway data are not rewritten by the authentication migration.

Whole-service backups contain the password hash and private account metadata; keep them private. Schema-7 AWM-ADM bundles can be verified/restored without modification and migrate when opened. Restores of account-bearing bundles preserve the administrator but revoke all sessions/scoped clients and reset credentials, advance the account generation and disable the legacy owner bypass. Provider authority and feeds are paused by the existing recovery procedure. Sign in with the restored password or use local operator recovery. Model snapshots contain no account/credential data.

This is the existing loopback HTTP deployment, not a supported Internet-facing authentication service. Cookies are intentionally not `Secure` on local HTTP. Same-origin Host/Origin checks, JSON-only mutations, cross-site rejection and CSRF checks apply throughout `/api/v1`. Reverse proxies/off-host exposure require a separate TLS and authentication design. Compromise of the local operator or host is outside this boundary; it already permits access to the stores and recovery material.
