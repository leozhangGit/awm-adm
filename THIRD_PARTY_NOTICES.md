# Third-party notices

Original AWM-ADM code and documentation are provided under the [MIT License](LICENSE). Dependency and bundled-material licenses are not replaced by that license.

## Docker/Moby seccomp profile

`deploy/docker-default-seccomp.json` is the Docker/Moby default seccomp profile from the source revision recorded in [seccomp-provenance.json](deploy/seccomp-provenance.json). `deploy/app-seccomp.json` is an adapted profile that restricts application egress. The upstream Apache-2.0 text is retained verbatim in [docker-profiles-LICENSE](deploy/docker-profiles-LICENSE). The provenance file records the source hash, changes and resulting hash. Preserve these notices with redistributed profiles.

## Runtime and build dependencies

Python and JavaScript dependencies retain their upstream licenses. Exact package versions and artifact hashes are pinned in [uv.lock](uv.lock) and [package-lock.json](console/package-lock.json). [Dependency inventory](docs/dependency-inventory.json) records publisher license metadata; it is not a substitute for upstream license text or a vulnerability audit.

Docker images include pinned Python/Node/uv bases and a checksum-verified Lean compiler. Lean and its bundled components retain the notices supplied by their distributions; see [Lean's license](https://github.com/leanprover/lean4/blob/v4.19.0/LICENSE). Toolchain identities are in [deploy/](deploy/). Preserve upstream notices when redistributing images or dependencies.

## Scientific reference

The Algebraic World Model paper is a conceptual reference, not a bundled third-party implementation. See [references](docs/REFERENCES.md). The finite engine and its compatibility fixtures are maintained in this repository.
