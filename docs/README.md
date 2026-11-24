# Documentation

AWM-ADM 0.4.0 is a single-owner service. Start with the [repository README](../README.md) and [installation guide](INSTALLATION.md).

For the motivation and conceptual architecture, read [Explore AWM-ADM](https://concourses.net/awm-adm.html). The [foundation reference](REFERENCES.md) separates AWM's method from our ADM design choices and implementation guarantees. All build and operating instructions are contained in this repository.

## Use the service

| Guide | Covers |
| --- | --- |
| [Installation](INSTALLATION.md) | Docker build/start, direct workspace access, configuration and troubleshooting |
| [Local workspace](LOCAL_ACCESS.md) | Login-free console/API, local boundary and preserved data |
| [Console](CONSOLE.md) | Models, direct Ask/Teach, search, history and status |
| [Ask](ASK.md) | Interpretation, local execution, explanation and unknown results |
| [Knowledge intent](KNOWLEDGE_INTENT.md) | Adopted rules, sourced facts, scoped premises and exploratory material |
| [Meaning and temporal context](TEMPORAL_INTERPRETATION.md) | System timezone, calendar-date lookup, source precision and historical presentation |
| [Teaching](TEACHING.md) | Goals, clarification and automatic checked learning |
| [Preparation readiness](PREPARATION_READINESS.md) | Missing information, capability limits and resumable clarification |
| [Teaching execution](TEACHING_EXECUTION.md) | Admission, cancellation, completion and recovery |
| [Teaching change reports](CHANGE_REPORTING.md) | Checked before/after meanings, preserved dependents and bounded publication reports |
| [Attachments and intake](INTAKE.md) | Supplied files and managed push queues |
| [History](HISTORY.md) | Time-filtered console/API activity and current knowledge search |
| [Model lifecycle](MODEL_LIFECYCLE.md) | Independent snapshots, mode changes, archive and deletion |
| [Connection](CONNECTION.md) | Enable/Disable, saved keys, token and call charts |
| [Provider failures](PROVIDER_FAILURES.md) | Preparation deadline, precise transport diagnostics and uncertain outcomes |
| [Operations](OPERATIONS.md) | Backups, restore, diagnostics, retention and upgrade boundaries |

## Integrate and inspect

| Reference | Covers |
| --- | --- |
| [Codex project plugin](../codex-plugin/README.md) | Local setup, project bindings, Ask/Teach and explicit revision |
| [API](API.md) and [OpenAPI](../contracts/openapi.json) | Unified `/api/v1` model and chat APIs |
| [Conversations](CONVERSATIONS.md) | Direct messages, automatic context and durable provenance |
| [Learning](LEARNING.md) | Manual bounded acquisition and provider transport |
| [Language preview](LANGUAGE.md) | Explicit interpretation preview and confirmation |
| [Typed temporal evidence](TEMPORAL_EVIDENCE.md) | Mixed time meanings, attributed reports, local queries and compatibility |
| [Evidence recall](EVIDENCE_RECALL.md) | Bounded reads across saved scopes, exact provenance and retrieval versus new computation |
| [Sources](SOURCES.md) | Immutable evidence, extraction, facts and corrections |
| [Feeds](FEEDS.md) | Bounded source processing and coverage |

## Understand and contribute

- [Architecture](ARCHITECTURE.md), [runtime](RUNTIME.md), [finite engine](ENGINE.md)
- [Service contracts](SERVICE_CONTRACTS.md), [chat contracts](CHAT_CONTRACTS.md), [workflow lifecycle](WORKFLOW_LIFECYCLE.md), [limits](LIMITS.md)
- [Testing](TESTING.md), [contributing](../CONTRIBUTING.md), [security](../SECURITY.md)
- [Release scope](RELEASE.md), [references](REFERENCES.md), [third-party notices](../THIRD_PARTY_NOTICES.md)

Versioned routes, storage schemas and serialized profiles are compatibility identifiers, not separate installed products. All guides describe the same AWM-ADM 0.4.0 release.
