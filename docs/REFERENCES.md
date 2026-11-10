# References and implementation provenance

## Conceptual foundation

The conceptual source is [Algebraic World Model: From Exploration to Proofs, arXiv:2610.40503v1](https://arxiv.org/html/2610.40503v1), by Guancheng Pan, Qixin Tan, Yang Yuan and Andrew C. Yao.

### What the paper proposes

AWM uses LLM agents to explore environments, test executable hypotheses, organize them into typed objects and rules, simplify their structure and construct Lean proofs. Its models describe particular environments, including individual games; a single theory of the whole world is not required. Read §§2–3 and the Statement on AI use for these aspects of the method. Proofs establish conclusions under a model's premises; the fit between those premises and the environment requires separate examination (§§4.4 and 6). [Source paper](https://arxiv.org/html/2610.40503v1)

### What this project designs

AWM-ADM adopts explicit, inspectable models as its foundation and organizes them into a service with independently maintained instances. The following are ADM engineering choices, rather than requirements attributed to the paper:

- Empty or checked-snapshot initialization, independent ownership and versioned evidence/history.
- A separation between fallible acquisition/conversational presentation and authoritative execution against accepted models.
- Receiver-ordered forward/backward conflict policies, with mode changes applying only to future decisions.
- Owner requirements, bounded background jobs, admission controls, spending limits, APIs and a conversational console.

The role assigned to LLMs here is a service boundary, not a claim that AWM excludes LLM reasoning. AWM's value is a project design premise; this implementation does not establish comparative superiority or reproduce the paper's experiments. The [project introduction](https://concourses.net/awm-adm.html) explains the motivation and architecture.

### Implementation and verification scope

The finite grammar, bounded algorithms and generated invariant-certificate templates are this implementation's verification profile. It does not implement the paper's complete exploration, transformation and proof pipeline. Lean kernel checks and exhaustive correspondence to executable representations are reported separately; the Python interpreter and translator remain trusted. Small domains and accepted premises do not by themselves establish external truth.

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
