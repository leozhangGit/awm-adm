# Automatic teaching execution

A clear local Teach submission authorizes preparation, acquisition and checked admission within its expressed meaning. The service creates an immutable `awm-adm-teaching-specification/2`, then starts an `awm-adm-teaching-execution/2` automatically. Ordinary users do not approve a preparation and then separately approve every candidate. A genuine semantic or protected-setting decision still requires clarification.

## Checking and publication

The parent visits dependent children in order. Acquisition and diagnostic revision take place in private drafts. Only complete candidates pass to the existing local admission checks. Installed independent requirements remain mandatory; an empty policy makes no domain-conformance claim and does not disable automatic publication. Provider-proposed requirements cannot become independent authority automatically.

Publication commits the accepted revision, evidence support, receiver receipt decision, child outcome and parent’s current context in one ADM transaction. The parent is checked before dispatch and again after local computation, immediately before publication. Cancellation, deletion or a changed model/owner/connection context can prevent publication. Forward/backward precedence and dependency validation are unchanged. A conflict rejection is not retried to evade precedence.

For a conversational correction, preparation closes each child's interfaces over the accepted transitive dependent graph. Dependencies not explicitly revised are pinned by their declaration hashes in the immutable child task. Their exact bodies seed private construction; provider updates cannot change or discard them. New candidate artifacts record structural reuse and the source theory/declaration hashes, then undergo ordinary full admission and independent requirements. No old certificate is imported. Shared dependent corrections must use one atomic child. Unsupported reconstruction or exceeding the existing declaration bound stops preparation rather than dropping dependents or enlarging scope. The raw engine and explicit low-level candidate APIs retain their ordinary dependency-retirement semantics.

Automatic source admission records the local Teach task and local checks. It does not fabricate candidate-specific human review. Exact source versions, byte spans, corrections, intervals and unknown/disputed support remain part of the evidence machinery.

## Work and stopping

Each acquisition child has at most two diagnostic attempts, a finite private draft and no-progress stopping. Per-call token/time bounds and per-computation work/time bounds remain enforced. The active execution has a 15-minute operational deadline; preparation has a five-minute exchange deadline. These bound running work, not a user’s idle clarification response. See [limits](LIMITS.md) for the configured envelopes.

A task can succeed, partially succeed, fail, exhaust its finite work, be cancelled or need input. Accepted independent children survive a later unresolved child. No task promises to close its knowledge gap, changes providers silently, or repeats a call with an unknown outcome.

The chat’s **Stop** action cancels the exact interaction. The explicit task-command API additionally retains pause/resume/cancel and source-intake finish controls. Pause prevents new dispatch and publication; already dispatched work can return. Resume uses the same task scope and active-work deadline. Cancellation remains possible after context changes and preserves accepted knowledge.

## Completion and recovery

A deterministic summary reports accepted and unresolved objectives, vocabulary installation, available local follow-up and explanation availability. A provider may narrate that bound summary in ordinary language, preserving necessary and sufficient conditions precisely. A fully successful task shows one explanation with a short learned-and-saved count; unresolved work, vocabulary problems and local follow-up outcomes retain the complete checked summary. Exact accepted objectives remain available in the task record. Invalid or failed narration cannot erase the checked outcome. It is not a source of new knowledge.

Stable child creation intents prevent duplicate episodes after lost acknowledgments. Startup retains known work and accepted children. Unfinished preparation and uncertain outbound handoffs stop without automatic redispatch. Completion narration is not repeated on restart. Historical manual preparations remain readable and require a new ordinary submission to continue.

Vocabulary is checked against accepted declarations before installation. Existing internally bound local-query follow-up preserves the original request and creates a separately identified new result. Ordinary Ask gaps remain unknown until the user chooses to teach; they do not automatically initiate acquisition.

[Change reports](CHANGE_REPORTING.md) compare the checked before/after definitions and evidence for acquisition and source publications. Completion distinguishes a changed definition, an unchanged dependent rechecked with updated bindings, evidence-only updates and active removals. Reports retain exact publication revisions and explicitly mark missing or abbreviated details. The existing narration call explains this packet; no additional provider call or query is needed.

The parent retains checked publication effects in the same transaction as each child result. Removed dependents make that objective unresolved even when some declarations were saved. Completion records list actual saved declarations for such a partial child, with the missing capability reported separately. Local post-publication failures or unsuccessful original-query follow-up are explicit unresolved work; narration cannot promote them to success. Provider narration failure alone does not erase otherwise completed learning.

Language setup derives a validated revision-compatible profile, recording omitted obsolete metadata. Catalog reads derive the same compatible view without editing historical profiles. A missing target removes its whole alias rather than silently selecting a surviving alternative; invalid parameter/value metadata is omitted without fabricating replacement meaning. New explicit vocabulary writes remain strict. A retained malformed binding cannot make otherwise valid repair teaching depend on first editing the language settings manually. Work exhaustion remains a failure, not permission to omit unchecked metadata.

Preparation also reconciles inherited metadata against explicitly proposed interfaces, so a renamed or removed parameter cannot be blocked by its old label. New provider-proposed metadata is validated strictly against those interfaces; it cannot use reconciliation to hide an invalid target.

## API and implementation

Normal clients use `/adms/{adm}/teach` and read `/interactions/{id}`. Advanced task commands at `/tasks/{id}/commands` retain exact specification/context/version bindings. Historical manual review fields remain readable; automatic tasks use checked admission and truthful task provenance. There is no financial renewal endpoint.

See [execution coordinator](../src/awm_adm/teaching/execution.py), [direct interaction service](../src/awm_adm/interaction/service.py), [intake](INTAKE.md) and [learning](LEARNING.md). Python scheduling, interpretation and transaction code remain trusted implementation, not a formally verified end-to-end program.
