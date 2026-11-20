---
name: adm-setup
description: Diagnose AWM-ADM plugin readiness, project selection, local service availability or a missing native tool connection. Use for setup or recovery rather than normal Ask/Teach work.
---

# AWM-ADM readiness

Use native `adm_status` with Codex's explicit selected project path. If no project is selected, tell the user to open or choose one; do not infer it from the plugin working directory. With several plausible roots, ask which one. Status never creates a model or tests the external LLM connection.

Explain the returned condition and the next relevant step:

- No native tools: check that the AWM-ADM plugin is enabled and its installed runtime is prepared. A fresh chat or app restart may be needed after installation. Do not substitute Terminal/HTTP for missing tools.
- Service unavailable: the login-free console and API should be running at `http://127.0.0.1:9527/`. Do not silently try an old port, another host or a redirect.
- Connection not ready: ask the user to open Connections and enable their provider. The plugin needs no administrator login, service API key, allowance or session renewal. Never request or read their provider key.
- No binding: when the user wants to use AWM-ADM for this selected project, call `adm_project`. It creates an empty backward-mode model named after the project, or recovers the same pending creation.
- Missing model or changed installation: explain the mismatch and obtain an explicit model/rebinding choice. Do not pick by name or erase the private journal to force a new creation.
- Interrupted work: inspect its retained `adm_work` identity. Recovery uses the same submission; uncertain work is not a reason for a fresh attempt.

Use only the plugin's relevant native operations. Provider settings, deletion, imports and other console capabilities remain in the console. Installation changes are a separate user request, not a side effect of readiness. The public [plugin guide](../../README.md) describes installation and private state.
