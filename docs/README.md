# Documentation

AWM-ADM 0.3.0 is a single-owner service. Start with the [repository README](../README.md) and [installation guide](INSTALLATION.md).

For the motivation and conceptual architecture, read [Explore AWM-ADM](https://concourses.net/awm-adm.html). The [foundation reference](REFERENCES.md) separates AWM's method from our ADM design choices and implementation guarantees. All build and operating instructions are contained in this repository.

## Use the service

| Guide | Covers |
| --- | --- |
| [Installation](INSTALLATION.md) | Docker build/start, first administrator, configuration and troubleshooting |
| [Administrator](ADMINISTRATOR.md) | Password login, setup credentials, sessions and local recovery |
| [Console](CONSOLE.md) | Models, direct Ask/Teach, search, history and status |
| [Ask](ASK.md) | Interpretation, local execution, explanation and unknown results |
| [Meaning and temporal context](TEMPORAL_INTERPRETATION.md) | System timezone, calendar-date lookup, source precision and historical presentation |
| [Teaching](TEACHING.md) | Goals, clarification and automatic checked learning |
| [Teaching execution](TEACHING_EXECUTION.md) | Admission, cancellation, completion and recovery |
| [Attachments and intake](INTAKE.md) | Supplied files and managed push queues |
| [History](HISTORY.md) | Time-filtered console/API activity and current knowledge search |
| [Model lifecycle](MODEL_LIFECYCLE.md) | Independent snapshots, mode changes, archive and deletion |
| [Connection](CONNECTION.md) | Enable/Disable, saved keys, token and call charts |
| [Operations](OPERATIONS.md) | Backups, restore, diagnostics, retention and upgrade boundaries |

## Integrate and inspect

| Reference | Covers |
| --- | --- |
| [API](API.md) and [OpenAPI](../contracts/openapi.json) | Unified `/api/v1` model, administrator and chat APIs |
| [Conversations](CONVERSATIONS.md) | Direct messages, automatic context and durable provenance |
| [Learning](LEARNING.md) | Manual bounded acquisition and provider transport |
| [Language preview](LANGUAGE.md) | Explicit interpretation preview and confirmation |
| [Sources](SOURCES.md) | Immutable evidence, extraction, facts and corrections |
| [Feeds](FEEDS.md) | Bounded source processing and coverage |

## Understand and contribute

- [Architecture](ARCHITECTURE.md), [runtime](RUNTIME.md), [finite engine](ENGINE.md)
- [Service contracts](SERVICE_CONTRACTS.md), [chat contracts](CHAT_CONTRACTS.md), [workflow lifecycle](WORKFLOW_LIFECYCLE.md), [limits](LIMITS.md)
- [Testing](TESTING.md), [contributing](../CONTRIBUTING.md), [security](../SECURITY.md)
- [Release scope](RELEASE.md), [references](REFERENCES.md), [third-party notices](../THIRD_PARTY_NOTICES.md)

Versioned routes, storage schemas and serialized profiles are compatibility identifiers, not separate installed products. All guides describe the same AWM-ADM 0.3.0 release.
