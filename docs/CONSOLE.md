# Console guide

Open the workspace directly. Its four pages are Overview, Domain models, Connections and Operations. There is no login or account setup.

## Connect once

In **Connections**, select a provider, enter its model identifier and API key, then click **Enable**. A connection test runs; success enables that configuration for all remote capabilities. A failed test leaves it disabled and explains the failure. There is no separate permission, price or spending setup.

**Disable** stops new remote dispatch and makes the fields editable. The provider, model and saved key remain; leave the key unchanged to reuse it. Already dispatched work can still return. Enabling again does not repeat interrupted or uncertain work.

The charts show reported input/output tokens for seven calendar days and successful/failed calls for the last 24 hours. Unknown usage and unresolved outcomes are shown separately. See [Connection](CONNECTION.md).

## Models

Create an empty model or upload a snapshot. No domain selection is required. Imports receive an independent identity after their knowledge, evidence and requirements pass local checks. Overview shows readiness, example sandboxes and recent operations; the model collection is listed only in Domain models. Overview’s examples create ordinary independent sandbox models. Recent model operations lists up to 50 create/import/export/delete records received in the past seven days, newest first, with at most 10 operations per page. Previous/Next controls and a page/range indicator appear when there is more than one page. Background refresh preserves the selected page, moving to the last remaining page if the list shrinks. Deletions still in progress, including older ones, remain visible in a separate section with an explicit retry action if blocked. Domain models has no duplicate cleanup panel. The time window and display pagination do not delete records.

Each model has **Ask**, **Teach**, **Model & evidence**, **History** and **Settings**.

- **Ask:** type a question and send it. The provider interprets the request, the ADM executes supported operations, and the provider explains the checked outcome. Unknown, false and inconclusive results stay distinct. Ask does not start learning implicitly.
- **Teach:** describe a rule, capability or fact, optionally attaching text or Markdown. Clear requests proceed through acquisition and local validation automatically. Genuine ambiguity produces a question in the same chat. Automatic admission does not bypass independent requirements or conflict rules.
- **Model & evidence:** search current accepted declarations and supporting evidence by name, kind or text. There is no technical revision selector.
- **History:** search model activity by time, including console interactions and API requests. Related stages are grouped; recorded results retain the model bindings used when they ran.
- **Settings:** rename, change conflict mode, export/clone snapshots, archive or delete the model. Forward prefers later conflicting learning results; backward retains earlier knowledge. Switching applies to future decisions and does not reverse past decisions.

Ask and Teach each initially show their **most recent 100 exchanges**, in chronological order, in a keyboard-accessible scroll area capped at 60% of the viewport height. When older exchanges exist, **Load more** at the top adds up to 100 older exchanges per click and preserves the visible message's position. The button disappears when the earliest retained exchange is loaded. Refreshing or reopening a model/channel starts with its latest 100 again. New exchanges append to the open window; background polling refreshes that window without loading unrequested older history. All retained interactions remain searchable through **History**; display pagination does not delete them or change LLM context.

At the history’s top or bottom, continued scrolling naturally passes to the page so the composer and footer remain reachable. New replies follow automatically only while you are near the end; reading older messages keeps your position through background updates. Use **Jump to latest** to return to the newest message and resume following it. This control moves only the history, not the page. The service manages bounded context for individual exchanges; the transcript itself is not accepted knowledge. Replies remain associated with the originating exchange, even when it is outside the visible window, not whichever API request happened most recently. Drafts and selected files survive ordinary polling. An uncertain submission can be retried with the same identity without duplicating work.

Clear follow-ups can refer to the previous scenario without repeating every input. A new explicit value updates that scenario; missing or genuinely ambiguous details produce a question. Ordinary answers use conversational wording with a short independent model-answer label. Successful teaching uses one completion explanation and a learned-and-saved count. Incomplete learning, unknown answers and complex result limits remain visible. Exact diagnostic records are available through the API, and older messages retain their original wording.

Only selected material is processed by a Teach submission. Uploading alone does not teach. Source evidence remains an assertion about the world, not proof of external truth. See [Ask](ASK.md), [Teaching](TEACHING.md) and [History](HISTORY.md).

## Operations

**Operations** shows service health, storage, work in progress and retained request failures by model. It is a status dashboard. Work by model uses aligned numeric columns and row separators, with keyboard-accessible horizontal scrolling on narrow screens. Provider usage is in Connections; model outcomes are in History. Whole-service backup and recovery are operator procedures documented in [Operations](OPERATIONS.md).

The workspace opens directly, without a Login page or session renewal. Provider configuration remains in Connections. See [Local access](LOCAL_ACCESS.md).

The console presents ordinary model interaction. Structured execution, proof checks, independent requirements, explicit source/feed operations and diagnostic records remain available through the [API](API.md); removing their manual panels does not remove their capabilities.
