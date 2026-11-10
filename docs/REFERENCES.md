# References and implementation provenance

## Conceptual foundation

The project is inspired by [Algebraic World Model: From Exploration to Proofs, arXiv:2610.40503v1](https://arxiv.org/html/2610.40503v1). AWM is the project's chosen foundation. The local ADM design applies those ideas to bounded, independently maintained domain theories with separate acquisition and serving. This is a project design premise, not a universal comparison claim or reproduction of the paper's experiments.

The package owns its finite engine, runtime and test fixtures. Compatibility fixtures retain their exact artifact bytes; they are not a dependency on an external source checkout. [Architecture](ARCHITECTURE.md), [Engine](ENGINE.md) and [Testing](TESTING.md) describe the implemented scope and trusted-code boundary.

## Implementation references

| Component | Primary references |
| --- | --- |
| Local Lean kernel | [Lean 4.19.0](https://github.com/leanprover/lean4/releases/tag/v4.19.0); [pinned archive](../deploy/lean-lock.json) |
| Container services | [Docker Compose](https://docs.docker.com/compose/); [Dockerfile and base pins](../deploy/Dockerfile) |
| Application isolation | [Moby seccomp source](https://github.com/moby/profiles/blob/4b8214fc4971e06172938a1f1554ccff6647ee80/seccomp/default.json); [local provenance](../deploy/seccomp-provenance.json) |
| Password hashing and credential encryption | [cryptography Argon2id](https://cryptography.io/en/stable/hazmat/primitives/key-derivation-functions/#argon2id), [Fernet](https://cryptography.io/en/stable/fernet/), [RSA](https://cryptography.io/en/stable/hazmat/primitives/asymmetric/rsa/) |
| Authentication guidance | [OWASP authentication](https://cheatsheetseries.owasp.org/cheatsheets/Authentication_Cheat_Sheet.html), [password storage](https://cheatsheetseries.owasp.org/cheatsheets/Password_Storage_Cheat_Sheet.html) |
| HTTP and typed validation | [FastAPI](https://fastapi.tiangolo.com/), [Pydantic](https://docs.pydantic.dev/), [JSON Schema](https://json-schema.org/) |
| Provider transports | [OpenAI Structured Outputs](https://developers.openai.com/api/docs/guides/structured-outputs), [Anthropic Structured Outputs](https://platform.claude.com/docs/en/build-with-claude/structured-outputs) |
| Console build and checks | [React](https://react.dev/), [Vite](https://vite.dev/), [TypeScript](https://www.typescriptlang.org/), [Node TypeScript execution](https://nodejs.org/docs/latest-v22.x/api/typescript.html), [Prettier](https://prettier.io/docs/cli) |

Exact dependency versions and hashes are in the lock files and [dependency inventory](dependency-inventory.json). The linked documentation explains upstream interfaces; it does not certify this application, verify a provider account or establish current pricing. Shipped audited pricing profiles have explicit validity windows described in [Spending](PRICED_ALLOWANCES.md).

Original software is MIT-licensed. Bundled profiles and dependencies retain their own notices in [Third-party notices](../THIRD_PARTY_NOTICES.md).
