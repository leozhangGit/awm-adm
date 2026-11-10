# Console guide

The console at **http://127.0.0.1:8080/** is the owner interface for AWM-ADM 0.3.0. Sign in with the local administrator's email/password. The service hosts independent models, connections and operational controls in one workspace.

## Models

Create an empty model without choosing a predefined domain, or import a checked JSON snapshot. A snapshot receives a new independent model identity after content, evidence and requirements are checked. Example snapshots are authored fixtures and become ordinary instances when loaded.

Within a model, **Ask** and **Teach** have separate conversations and authority. **Model & evidence**, request history and **Settings** expose accepted content and owner controls. Settings supports naming, snapshot export/clone, future-only conflict-mode changes, independent requirements, archive and named deletion. See [Model lifecycle](MODEL_LIFECYCLE.md).

## Ask

Use **Set up interaction** to choose a supported priced connection and disclosure scope, answer the allowance question and confirm. A new question can then be interpreted by the provider and executed locally if its meaning is complete and supported. Clarification is requested when required. An optional AI explanation describes the local result; the displayed result and its original context remain authoritative.

Unknown facts stay unknown. A linked Teach conversation preserves the question but does not authorize funding or start learning. More detail is in [Ask](ASK.md).

## Teach

Describe the capability or supplied material. Attach Markdown/text/JSON/JSONL or select retained material, and explicitly permit disclosure when using the provider. Answer questions about scope and the task allowance.

Review the prepared meaning before **Start teaching**. The service coordinates bounded acquisition, diagnostics, extraction and checking. Candidate meaning or source claims can require owner review; approval does not bypass local validation. Completion distinguishes accepted work, unresolved objectives, vocabulary installation, optional narration and spending. A task can stop without closing its knowledge gap.

For an unchanged unstarted preparation, **Review more time** offers an explicit bounded time extension within the same caps and price. It does not repeat preparation or start execution. See [Teaching](TEACHING.md), [Execution](TEACHING_EXECUTION.md) and [Intake](INTAKE.md).

## Details and readiness

Ordinary chat displays readable outcomes. **Details** exposes exact specifications, context/revision bindings, provider usage, diagnostics and original records. Result values, uncertainty and meaningful decisions stay visible in the conversation.

Readiness identifies disabled remote access, connection purpose, unsupported/expired pricing and unavailable allowances before submission. Fixing readiness does not renew an allowance or send a pending message automatically. Unsent text is retained in tab-local session storage per model/channel/conversation when browser storage is available. Saved turns and accepted work persist on the server; a browser draft is not queued work.

Polling, reload and reconnect read existing work rather than redispatching it. A lost response can be recovered with its original submission identity. Changed context requires a newly reviewed action. Expired login returns to the account screen.

## Local debug

**Structured local execution** invokes accepted capabilities without an LLM: inspect capabilities, evaluate functions, check Boolean claims, plan, check certificates, explain saved results and look up historical facts. Forms derive from the selected model. Complex types can require a structured query. Resource limits bound computation and do not promise an answer.

Historical entity/predicate choices come from installed owner projection settings or checked accepted-snapshot metadata. An imported model does not need new source-intake permissions to query its existing history. The exact date and local query bind the result; unknown/out-of-coverage/disputed facts return a gap.

**Interpretation preview** preserves the explicit preview-and-confirm workflow. Local phrases have a bounded grammar; optional provider interpretation needs its own authority. Preview consent does not authorize separate chat spending. See [Language preview](LANGUAGE.md) and [API](API.md).

## Advanced model tools

These are manual engineering controls in the same 0.3.0 service, operating on the same models:

| Page | Purpose |
| --- | --- |
| Learning | Configure a bounded acquisition episode, connection, limits and publication policy; inspect diagnostics and review candidates. |
| Sources | Store immutable material, configure projection, perform explicit extraction, review facts/corrections and manage feeds. |

They are useful for inspection, controlled tests and direct administration. Actions can create actual learning/source work and consume authorized provider budgets. They retain the same local checks and cannot bypass a Teach task's parent authority. For ordinary interaction, use Ask and Teach.

## Connections, operations and accounts

Connections stores keys privately through the gateway, controls allowed purposes, reviews supported pricing, and configures separate spending lanes. Saving settings is local. **Test** is an explicit provider call with its own budget. Remote access and spending start disabled. See [Spending](PRICED_ALLOWANCES.md).

Operations shows bounded, sampled diagnostics and usage and offers backup/recovery instructions. Reports do not themselves stop services, delete evidence or grant remote authority. Follow [Operations](OPERATIONS.md) for paired backups.

Account changes the password and revokes browser sessions. **Forgot password?** uses a short-lived local operator recovery credential. See [Administrator](ADMINISTRATOR.md).
