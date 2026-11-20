# AWM-ADM

**Independent models. Checked learning. Reasoning you can inspect.**

AWM-ADM is a service for building and using **Algebraic Domain Models (ADMs)**: independently maintained models with explicit concepts, rules, evidence and supported operations. It combines LLM-assisted learning and conversation with an accepted model that can be inspected, revised and executed under its owner's control.

The project is inspired by [Algebraic World Model: From Exploration to Proofs](https://arxiv.org/html/2610.40503v1), which develops explicit models of particular environments and uses them for formal reasoning. Our focus is a practical service in which each ADM develops its own domain knowledge and history. A model can start empty or from a checked snapshot; the engine does not prescribe its domain. Equipment checkout, water tanks and access permissions are examples, not built-in restrictions.

An external LLM helps interpret requests, propose knowledge and explain outcomes. The ADM validates proposed changes and executes supported queries against its accepted model. Learning can continue in the background while accepted capabilities remain available. Provider output is fallible; only checked, admitted content becomes active knowledge, and fluent explanations remain separate from computed results.

Independent ownership, the learning/serving separation, forward/backward conflict policies and checked service workflows are **our ADM design choices**. AWM already uses LLM agents and environment-specific models; these choices describe how we apply its ideas. See [the foundation and implementation boundaries](docs/REFERENCES.md).

**[Explore AWM-ADM on concourses.net](https://concourses.net/awm-adm.html)** for the motivation, architecture and examples.

**Release: 0.4.0 · MIT license · Supported Docker target: Linux ARM64**

## The idea behind AWM-ADM

I want AI systems to develop knowledge that stays explicit, inspectable and consistently usable over time. As an assistant takes on more work, it should be clear which rules it has accepted, what evidence supports them and how new information can change them.

Context and harness engineering help organize information, tools and checks around an LLM. I want to complement that work with a maintained domain model: one whose supported consequences can be computed and checked independently of how the LLM interprets a conversation on any particular turn.

AWM-ADM is my first step toward that architecture. It combines the breadth and flexibility of an LLM with explicit domain knowledge, controlled learning and inspectable execution. The model can acquire new capabilities while proposed changes remain subject to independent owner requirements. It can also preserve a gap when the available knowledge does not support an answer.

The longer-term aim is for an ADM to become a **logic guide for an LLM-driven system**, supplying accepted rules and checked results that help shape its decisions. Possible future applications include software agents, workflow automation and robotic systems. Turning guidance into control would require application-specific integration that makes the relevant checks mandatory before an action can execute.

## What you can do

- **Ask** questions in a durable chat. The enabled provider interprets the request and explains the outcome; the ADM computes supported answers through its own engine.
- **Teach** capabilities through conversation and attach Markdown or text. A clear request starts learning and local validation automatically; the model asks when meaning or a necessary decision is unclear.
- **Use evidence over time.** Retain source provenance, dated facts and corrections. Missing evidence stays unknown. Managed push queues accept ongoing material within explicit limits.
- **Own independent models.** Create, name, clone, import/export snapshots, archive or delete a model. Each model has its own accepted theory and history.
- **Choose conflict behavior.** Backward mode retains earlier-arriving conflicting knowledge; forward mode prefers the later result, subject to validation and dependent-conclusion handling. Switching applies to future decisions.
- **Use checked knowledge.** Search accepted declarations and evidence, and find console/API activity in History. Structured API requests evaluate functions, check claims, plan and look up facts without a provider.

## Quick start with Docker

Requirements:

- An ARM64 host with Docker Engine/Desktop running Linux containers and Docker Compose v2. Apple Silicon is supported; AMD64 is not verified for this release.
- Python 3.10 or later on the host for the setup helper scripts. The Python 3.13 application, Node build and Lean 4.19.0 compiler are installed inside the images.
- Internet access for the initial dependency/toolchain build, and sufficient Docker disk space. A provider account is optional for local execution; normal Ask/Teach interaction requires a tested, enabled connection.

From the repository directory:

```sh
python3 scripts/setup_runtime.py
docker compose build
docker compose up -d --no-build --wait --wait-timeout 60
docker compose ps
```

Open **[http://127.0.0.1:9527/](http://127.0.0.1:9527/)**. The three services are the application, learning worker and provider gateway. Only the application is published, on loopback.

The workspace opens directly: no account, login, service API key or session renewal is required. The service trusts local access. Provider credentials belong only in Connections; they stay encrypted in the gateway and are never returned in ordinary reads. See [installation](docs/INSTALLATION.md) and the [local access boundary](docs/LOCAL_ACCESS.md).

## Your first model

1. Create an empty model under **Domain models**, or import a checked snapshot.
2. In **Connections**, choose the provider, enter its model identifier and API key, and click **Enable**. A successful connection test enables all remote capabilities.
3. Open **Teach** and describe what the model should learn. Attach text or Markdown when useful. Clear requests proceed automatically; answer any genuine clarification in the chat.
4. Open **Ask** to use accepted knowledge. Missing evidence stays unknown. Ask does not teach implicitly.
5. Search **Model & evidence**, review **History**, or use **Settings** for mode changes and snapshots.

The [teaching example](examples/teaching/README.md) supplies a small equipment rule and dated history. See the [console guide](docs/CONSOLE.md) and [connection guide](docs/CONNECTION.md).

Connections has one Enable/Disable control and usage charts. Disable retains the configuration and saved key while stopping new remote dispatch. No price installation, purpose permissions or spending setup is required. OpenAI and Anthropic transports are supported; the configured model must support their required structured responses. There is no automatic model switch or retry of an uncertain dispatched call.

## Use with Codex

The bundled [Codex plugin](codex-plugin/README.md) connects to this local service without a login or service API key. Within a selected project, Codex can create/reuse its model, teach adopted decisions and consult accepted knowledge through Ask. Mode changes require explicit user direction; forward remains active until the user requests backward. This is best-effort consultation, not a monitoring hook or enforcement gate.

## Stop, restart and protect data

```sh
docker compose stop
docker compose up -d --no-build --wait --wait-timeout 60
```

These commands preserve the named volumes. Keep `.local/secrets/` private: it includes the gateway encryption key needed to recover encrypted provider credentials. **Do not use `docker compose down -v` for normal shutdown; it deletes model and service storage.**

[Operational backup/restore](docs/OPERATIONS.md) captures both stopped storage owners. Model snapshots create independent models; they are not account/service backups. Recovery and updates must preserve uncertain provider reservations and accepted knowledge.

System timezone: Docker setup captures the host default automatically; native execution uses the service system default. Explicit user/source timezones take precedence. See [temporal interpretation](docs/TEMPORAL_INTERPRETATION.md) for date precision and replay semantics.

## Scope and guarantees

0.4.0 is a single-owner, single-host, loopback service with a bounded finite model language. Local acceptance checks enforce representation, independent owner requirements and configured admission rules. They do not establish that supplied premises are externally true. LLM interpretation and explanations remain fallible.

Lean kernel checking and exhaustive finite correspondence are reported separately. The interpreter and translator remain trusted code. Unknown provider usage stays reserved, and uncertain dispatched calls are not retried automatically. Finite execution limits bound each task; they do not guarantee that a requested capability can be learned.

Cluster reasoning, federation, Byzantine coordination, public internet hosting, multiple administrators, physical action execution, pull connectors, general PDFs/OCR and unrestricted theorem proving are outside this release. See [release scope](docs/RELEASE.md) and [security boundary](SECURITY.md).

## Documentation and development

- [Documentation index](docs/README.md)
- [Architecture](docs/ARCHITECTURE.md) and [finite engine](docs/ENGINE.md)
- [API reference](docs/API.md) and [OpenAPI](contracts/openapi.json)
- [Contributing and local checks](CONTRIBUTING.md)
- [Testing and assurance boundaries](docs/TESTING.md)

The repository builds and tests on its own. It does not import a parent project or require private development history. The public API uses `/api/v1`. URL versioning is independent of the **AWM-ADM 0.4.0** product version and the existing schema/profile and snapshot format identifiers.

## Foundation and license

AWM-ADM is an independent implementation inspired by AWM. The [references](docs/REFERENCES.md) distinguish the paper's method from this service's architecture and verification scope. This repository is not an official distribution of the paper's code or a reproduction of its experiments.

AWM-ADM is distributed under the [MIT License](LICENSE). Bundled third-party material retains its own notices; see [Third-party notices](THIRD_PARTY_NOTICES.md).
