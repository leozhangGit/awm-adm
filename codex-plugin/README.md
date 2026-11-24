# AWM-ADM for Codex

Maintain checked project knowledge through the local AWM-ADM service. Say **“Use AWM-ADM for this project”**, then work normally: Codex can teach adopted rules and decisions, recall accepted knowledge and check supported consequences. This plugin ships with AWM-ADM 0.4.0 and uses the same release version.

The console and API run at `http://127.0.0.1:9527/` without login or a service API key. Enable the provider once in the service's Connections page for Ask/Teach. Provider credentials stay in the service. There is no plugin spending/session setup.

Ask can recall relevant accepted evidence without a storage-time window, retaining units, subject scope and attribution. Teach guidance keeps subject knowledge separate from source-inspection metadata. A saved calculation is prior work; it is not a new model derivation. No additional native tool or setup is needed; the service provides the read path.

## Install

Requires the local AWM-ADM service, Python **3.13**, uv **0.13.7**, and Codex with native plugin support. The connector is a separate locked Python package; it does not import service internals. From the AWM-ADM repository root:

```sh
python3 codex-plugin/setup.py marketplace
codex plugin marketplace add .
codex plugin add awm-adm@awm-adm-local --json
```

The setup helper creates only `.agents/plugins/marketplace.json`; it refuses a different existing catalog. The native installer reports the installed package directory. Prepare that copy's runtime, replacing the example path below with the returned path:

```sh
python3 codex-plugin/setup.py runtime --installed /absolute/installed/plugin/path
```

This uses the lock file and installs non-editably into the installed package's `.venv`, independent of any active project environment or `UV_PROJECT_ENVIRONMENT` setting. It refuses unrelated package directories and recreates a copied virtual environment whose Python prefix points elsewhere. Initial dependency installation needs internet or a warmed uv cache. Nothing installs during a tool invocation. Keep the source checkout until the local marketplace is removed.

Start a fresh project chat; restart Codex if it still has the previous tool registry. Ask **“Check AWM-ADM for this project.”** Native tool availability is separate from skill visibility. The first **“Use AWM-ADM for this project”** creates an empty backward-mode model named after the selected project. No project means a reminder to select one, with no service/model/provider work.

## Work naturally

- “Remember that exports must retain the original identifiers.” Codex supplies useful scope and meaning through Teach, asking when something essential is unclear.
- “Would this proposed change fit our existing rule?” Ask interprets the question, executes supported reasoning locally and explains the result.
- “Switch to forward mode and replace that rule with this one.” This explicitly requests a mode change and a revision. All model checks still apply.
- “Return to backward mode.” Forward persists until you make this choice.

Backward mode learns compatible additions while preserving earlier conflicting content. Rejected replacement is not necessarily a logical contradiction. Unknown or unsupported answers remain gaps; an LLM explanation is never promoted to a checked answer. The plugin is best-effort assistance, not file monitoring or enforcement.

For a supported targeted correction, the service carries forward dependent definitions and checks the complete candidate again. A dependent declaration may receive a new stored identity even when its rule text is unchanged, because its dependency and evidence bindings changed. The [checked change report](https://github.com/leozhangGit/awm-adm/blob/main/docs/CHANGE_REPORTING.md) distinguishes changed definitions, preserved dependents, evidence updates and removals, with before/after meanings and publication bindings. Saved portions and unfinished work remain separate; incomplete reports are explicit. Preserving a definition does not preserve every conclusion it previously produced.

The project skill distinguishes adopted rules, sourced observations, explicitly adopted model premises and exploratory ideas. Fictional premises retain their model scope and are not presented as real-world facts; quotations, negations and hypotheticals are not relabeled to obtain acceptance. Users need no special wording or another approval for already clear intent. The skill prepares useful formalization, consults retained references across chats and follows work to completion or clarification. Codex manages identities and revisions; users need not write JSON or supply internal IDs. Direct attachment upload is not exposed; selected, relevant text can be taught through Codex, and the console supports attachments. The service owns source bookkeeping for pasted text and files. The connector preserves explicit reply links and returns bounded preparation diagnostics. A semantic clarification can be answered in conversation; an internal preparation failure should be diagnosed rather than repeatedly rephrased or presented as a missing mapping parameter. The service distinguishes missing information from a capability limit before learning: a missing date, unit, entity or bound can produce `needs_input` with a focused question, while an unsupported operation remains `unsupported`. Follow that question with the existing reply link; do not invent missing values or describe a missing-input question as a permanent model limitation. The service retains a structured provider-proposed assessment for diagnostics, without changing plugin tools or authority.

Teach can retain mixed instant observations, uncertain occurrences, interval validity, period values and attributed reports in one ADM. Ask preserves their distinct meaning and units through the service; plugin tool signatures stay the same. Unsupported partial interval revisions preserve accepted coverage and are reported without automatic rephrasing or retries.

Before passing a missing-fact question to you, Codex checks relevant project material and researches cited or authoritative sources with its available tools. It carries supported content and references into the existing Teach clarification, labels derived answers with their premises and assumptions, and preserves source attribution, precision and uncertainty. It still asks when evidence is unavailable or conflicting, or when a decision about intent, scope or representation belongs to you. Research remains within the requested task; it does not change modes, retry uncertain calls or turn an Ask into teaching. This is skill guidance for Codex, not a web-fetching capability added to the service or a guarantee of source truth.

Recalling an accepted definition through `adm_work` needs no provider call. A new natural-language Ask uses the service's interpretation and explanation workflow. Starting another chat reuses the project binding; it does not create another model or relearn the saved knowledge.

## Tools and state

| Tool | Purpose |
| --- | --- |
| `adm_status` | Read readiness and the selected project's binding. |
| `adm_project` | Create/reuse the project model, or explicitly bind a user-selected model. |
| `adm_ask` | Submit a question or a known Ask continuation. |
| `adm_teach` | Teach adopted knowledge or reply to a known Teach clarification. |
| `adm_work` | Follow/cancel retained work, recall references or search accepted knowledge. |
| `adm_set_mode` | Apply an explicit user-directed forward/backward change. |

Private bindings and work journals live under `~/.local/share/awm-adm-codex/`, outside the repository, with private file permissions. They contain selected text, model references and results, never provider keys. Canonical project paths plus filesystem identity distinguish projects; names do not. Renames/recreated directories may require explicit rebinding. Preserve journals during recovery: deleting one can lose the identity of work whose acknowledgement was interrupted. A copied service backup can retain the same installation identity; this is local target checking, not remote authentication.

If model creation fails, status reports that failure and retains its original operation. After fixing the cause, say “Try creating this project's model again.” Codex uses `adm_project(retry_creation=...)` with the failed operation's reference only when the service confirms that no model was allocated. The old receipt is preserved, and repeated recovery of that retry creates at most one new model. Pending or uncertain work is reconciled under its existing identity; no retry loop runs in the background.

The journal holds up to 1,024 message intents and 8 MiB per project. On a capacity/corruption error, preserve it and resolve pending work before archiving completed records. Never discard uncertain intents to force a retry. Service history remains in the console/API. Uninstalling the plugin leaves models and these journals intact.

Only loopback HTTP is accepted; redirects, off-host resolution, proxy environment settings and cookies are not used. The default is fixed at port 9527. An intentional alternate loopback deployment must set `AWM_ADM_URL` for the plugin process and coordinate the service configuration. There is no fallback to port 8080. The plugin does not expose generic HTTP, provider configuration, deletion, snapshots, requirements or raw candidate admission. Local service access itself is trusted; tool scope is not a credential security boundary.

## Verify and uninstall

From `codex-plugin/`:

```sh
uv sync --locked --no-editable
.venv/bin/python -I -m unittest discover -s tests -v
```

These checks use synthetic service responses and the real MCP stdio protocol; no provider key is used. The service's integration tests additionally run real Ask/Teach orchestration, local validation and admission with recorded providers. A successful offline test does not establish live acquisition reliability.

```sh
codex plugin remove awm-adm@awm-adm-local
codex plugin marketplace remove awm-adm-local
```

These commands target only this plugin and marketplace. Remove the generated `.agents/plugins/marketplace.json` only if it still matches this package's catalog. Do not remove other Codex configuration, shared caches or the service's data. Reinstallation can reuse the preserved private binding.

## Preparation failures

The service allows three minutes by default for teaching preparation and reports specific failures through the existing `failure_code`, `failure_diagnostics` and summary fields. A timed-out call does not imply that the connection was disabled or that the model rejected the supplied knowledge. The connector preserves the dispatch identity, recorded timing and usage uncertainty without retrying. Polling or identical resubmission retrieves the same work; an explicit new attempt is separate work. Plugin tool signatures and installation do not change for this service behavior.

Source-processing failures include structured child reasons in the retained work result. Distinguish empty extraction, incomplete evidence, queue expiry and an uncertain provider timeout; skipped language setup is a consequence of unfinished learning. Polling does not retry a call. The service carries selected clarification material through extraction and preserves its original provenance; clients need not concatenate source files or repeat the original request manually.
