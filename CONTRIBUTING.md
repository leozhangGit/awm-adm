# Contributing

AWM-ADM is a standalone Python/TypeScript product. Read [architecture](docs/ARCHITECTURE.md), [service contracts](docs/SERVICE_CONTRACTS.md) and the relevant feature guide before changing behavior. Keep examples domain-specific and the engine domain agnostic.

## Development environment

Use Python **3.13**, Node **22.12+ within major 22**, and npm **10**. From this repository:

```sh
make bootstrap
make check
make build
make isolate
```

`make bootstrap` installs locked dependencies and warms local caches. `make check` runs lint/format, independence and publication checks, generated schemas, Python tests, native Node tests, TypeScript and the production console build. `make build` creates the wheel/assets. `make isolate` uses the public export boundary, installs non-editably into a temporary directory, and tests/builds offline from the warmed caches. No parent workspace is mounted or imported.

To include real kernel checks on the host, install Lean **4.19.0** and set its absolute executable path:

```sh
export AWM_ADM_LEAN=/absolute/path/to/lean
make check
```

Without this variable, real-Lean tests explicitly skip. Skips do not establish proof verification. The supported Docker app includes the checked Linux ARM64 compiler.

For an offline container test run:

```sh
docker build --target test -t awm-adm-test:0.3.0 -f deploy/Dockerfile .
docker run --rm --network none --read-only --cap-drop ALL \
  --security-opt no-new-privileges --pids-limit 256 --memory 5g --cpus 3 \
  --tmpfs /tmp:rw,size=1073741824,mode=1777 awm-adm-test:0.3.0
```

The test image is separate from normal runtime volumes. Automated provider tests use synthetic/recorded responses; no API key is needed.

## Working on the console

Run npm commands from `console/`, or use the Makefile. `make dev-api` and `make dev-console` expose a status-only preview and Vite workspace; they are not the complete runtime. Use a separate Docker project and loopback port for full integration work. Cookies are not port-scoped, so use distinct hostnames for simultaneous administrator sessions.

Ordinary chat shows readable outcomes; full payloads belong in Details. Preserve user drafts on background reads and never turn polling, focus or an unchanged retry into new paid work.

## Contracts and verification

- Preserve API paths and existing artifact/profile encodings. Update generated OpenAPI/schemas when an intentional contract change requires it.
- `make schemas` regenerates the boundary schemas and public OpenAPI offline. The API regression suite checks the committed OpenAPI against the running router.
- Keep model-neutral acquisition guidance, owner requirements, local validation, result bindings, receipt-order conflict handling and future-only mode switches.
- Add meaningful regression coverage for behavior changes. Use independent expected results; examples and provider proposals are not their own acceptance authority.
- Use a dedicated `awm-adm-check-*` project for runtime rehearsals. Never use a user's model or normal data volume as a destructive fixture.
- A live provider trial requires explicit scope, disclosure and budgets. Failed/uncertain calls retain conservative accounting and are never automatically repeated.

## Source release

```sh
python3 scripts/export_release.py /absolute/new/path/awm-adm-0.3.0
python3 scripts/export_release.py /absolute/new/path/awm-adm-0.3.0 --verify
```

The exporter includes an explicit public file set, excludes private stores/caches/credentials and records a SHA-256 inventory. It rejects source symlinks. This inventory is an integrity check, not a signature or proof of tests. Build/install from an exported directory without depending on files beside this repository.

Keep plans, personal trial transcripts/screenshots, local databases and operational credentials out of commits. Public documentation images belong under `docs/images/` and must be reviewed for private content and metadata before inclusion. `.gitignore` protects normal local paths, but review `git status` and staged content before publication. Do not force-add ignored files. See [security](SECURITY.md) for reporting sensitive findings.
