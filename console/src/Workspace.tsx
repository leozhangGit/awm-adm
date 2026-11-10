import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError } from "./api.ts";
import { forgetOutbox } from "./Lifecycle.tsx";
import { Notice } from "./components.tsx";
import {
  dollars,
  inlineParts,
  sameContext,
  workLabel,
  recoveryAdvice,
} from "./chat.ts";
import { TeachingTask } from "./TeachingTask.tsx";
import { readDraft, saveDraft } from "./draft.ts";
import type { TeachingTaskRecord } from "./TeachingTask.tsx";
import type { Adm } from "./types.ts";

type Context = Record<string, string | number>;
type Material = {
  id: string;
  name: string;
  byte_count: number;
  supersedes_version?: string;
  version_id?: string;
  current_source_version?: string | null;
};
type Turn = {
  id: string;
  author: string;
  text: string;
  created_at_ms: number;
  attachment_ids: string[];
};
type ReadinessIssue = { code: string; message: string; action: string };
type Question = {
  kind: string;
  id: string;
  question: string;
  expires_at_ms: number;
  context: Context;
};
type TeachingSpec = {
  objective: string;
  interface_review: string[][];
  plan: {
    summary: string;
    kind: string;
    requirements: unknown;
    children: {
      kind: string;
      objective: string;
      material: null | {
        projection: {
          entities: string[];
          predicates: {
            symbol: string;
            unit: string;
            kind: string;
            minimum: number;
            maximum: number;
            values: string[];
          }[];
          cells: {
            effective_from: string;
            effective_to: string | null;
            granularity: string;
          }[];
        };
        sources: { attribution: string }[];
      };
    }[];
  };
  budget: { cap_micro_usd: number };
};
type Proposal = {
  kind: string;
  id: string;
  context: Context;
  payload_digest: string;
  expires_at_ms: number;
  payload: {
    specification?: TeachingSpec;
    purpose?: string;
    connection_name: string;
    model: string;
    cap_micro_usd: number;
    disclosure: string;
    max_calls: number;
    max_input_tokens: number;
    call_input_bound?: number;
    max_output_tokens: number;
    expires_at_ms: number;
  };
};
type Conversation = {
  id: string;
  channel: string;
  title: string;
  created_at_ms: number;
};
type Detail = Conversation & {
  context: Context;
  items: Turn[];
  next_cursor: number;
  has_more: boolean;
  questions: Question[];
  proposals: Proposal[];
  readiness: string;
  readiness_issues?: ReadinessIssue[];
  stale_proposal_count: number;
  work: {
    id: string;
    status: string;
    dispatch_status?: string;
    flow?: string;
    local_status?: string;
  }[];
  tasks: TeachingTaskRecord[];
  presentations: {
    id: string;
    turn_id: string;
    status: string;
    explanation: string | null;
    fallback_reason: string | null;
    local_status: string;
  }[];
};
type Option = {
  price_id: string;
  name: string;
  model: string;
  synthetic: boolean;
  can_narrate: boolean;
};
type Submission = { path: string; body: Record<string, unknown> };

function RichText({ text }: { text: string }) {
  return (
    <div className="chat-prose">
      {inlineParts(text).map((p, i) =>
        p.kind === "strong" ? (
          <strong key={i}>{p.text}</strong>
        ) : p.kind === "code" ? (
          <code key={i}>{p.text}</code>
        ) : (
          <span key={i}>{p.text}</span>
        ),
      )}
    </div>
  );
}

export function Workspace({
  adm,
  channel,
  conversationId,
  select,
  teach,
}: {
  adm: Adm;
  channel: "ask" | "teach";
  conversationId: string;
  select: (id: string) => void;
  teach: (id: string) => void;
}) {
  const base = `/adms/${adm.id}`;
  const [conversations, setConversations] = useState<Conversation[]>([]);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [text, setText] = useState("");
  const [error, setError] = useState("");
  const [attachments, setAttachments] = useState<Material[]>([]);
  const [retained, setRetained] = useState<Material[] | null>(null);
  const uploadScope = useRef("");
  uploadScope.current = `${adm.id}:${channel}:${conversationId}`;
  const [discloseFiles, setDiscloseFiles] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [queueSetup, setQueueSetup] = useState(false);
  const [readError, setReadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [options, setOptions] = useState<Option[] | null>(null);
  const [spending, setSpending] = useState(false);
  const [optionIssues, setOptionIssues] = useState<ReadinessIssue[]>([]);
  const [technical, setTechnical] = useState<unknown>(null);
  const [showDetails, setShowDetails] = useState(false);
  const [outbox, setOutbox] = useState<Submission | null>(null);
  const identity = useRef<Submission | null>(null);
  const composer = useRef<HTMLTextAreaElement>(null);
  const detailsPanel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (showDetails) {
      detailsPanel.current?.focus();
      detailsPanel.current?.scrollIntoView({ block: "start" });
    }
  }, [showDetails, technical]);
  useEffect(() => {
    setAttachments([]);
    setRetained(null);
    setDiscloseFiles(false);
  }, [adm.id, channel, conversationId]);
  const storageKey = `adm-chat-outbox:${adm.id}:${channel}:${conversationId}`;
  const draftKey = `adm-chat-draft:${adm.id}:${channel}:${conversationId}`;
  const editText = (value: string) => {
    setText(value);
    try {
      saveDraft(sessionStorage, draftKey, value);
    } catch {
      /* Browser storage is optional. */
    }
  };
  const requestApi = <T,>(path: string, body?: unknown) =>
    api<T>(path, { method: body ? "POST" : "GET", body });

  const load = useCallback(
    async (signal?: AbortSignal) => {
      const list = await api<{ items: Conversation[] }>(
        `${base}/conversations?channel=${channel}&limit=100`,
        { signal },
      );
      setConversations(list.items);
      if (!conversationId) {
        setDetail(null);
        return;
      }
      let page = await api<Detail>(
        `${base}/conversations/${conversationId}?limit=100`,
        { signal },
      );
      if (page.channel !== channel)
        throw Error(
          "This conversation belongs to the other channel. Choose a conversation below.",
        );
      if (page.has_more) {
        const more = await api<Detail>(
          `${base}/conversations/${conversationId}?limit=100&after=${page.next_cursor}`,
          { signal },
        );
        page = { ...more, items: [...page.items, ...more.items] };
      }
      setDetail(page);
    },
    [base, channel, conversationId],
  );
  useEffect(() => {
    setDetail(null);
    try {
      setText(readDraft(sessionStorage, draftKey));
    } catch {
      setText("");
    }
    setError("");
    setOptions(null);
    setShowDetails(false);
    identity.current = null;
    try {
      setOutbox(JSON.parse(sessionStorage.getItem(storageKey) || "null"));
    } catch {
      setOutbox(null);
    }
    const controller = new AbortController();
    let running = false;
    const refresh = async () => {
      if (running) return;
      running = true;
      try {
        await load(controller.signal);
        if (!controller.signal.aborted) setReadError("");
      } catch (e) {
        if (!controller.signal.aborted) {
          if (e instanceof ApiError && e.code === "gone") {
            setDetail(null);
            setOutbox(null);
            forgetOutbox(adm.id);
          }
          setReadError((e as Error).message);
        }
      } finally {
        running = false;
      }
    };
    void refresh();
    const timer = setInterval(() => void refresh(), 2500);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, [load, storageKey]);

  async function submit(
    path: string,
    body: Record<string, unknown>,
    retain = true,
  ) {
    if (busy) return;
    setBusy(true);
    setError("");
    const payload: Submission = { path, body };
    identity.current = payload;
    if (retain) {
      setOutbox(payload);
      try {
        sessionStorage.setItem(storageKey, JSON.stringify(payload));
      } catch {
        /* Server replay identity remains authoritative. */
      }
    }
    try {
      const saved = await requestApi<{ id?: string }>(path, body);
      if (retain) {
        sessionStorage.removeItem(storageKey);
        setOutbox(null);
      }
      identity.current = null;
      if (path.endsWith("/messages")) {
        editText("");
        setAttachments([]);
        setDiscloseFiles(false);
      }
      setOptions(null);
      await load();
      composer.current?.focus();
      if (path.endsWith("/teach") && saved.id) teach(saved.id);
    } catch (e) {
      setError(
        (e as Error).message +
          " " +
          recoveryAdvice(e instanceof ApiError ? e.code : undefined),
      );
    } finally {
      setBusy(false);
    }
  }
  async function create() {
    setBusy(true);
    setError("");
    try {
      const saved = identity.current;
      const body =
        saved?.path === `${base}/conversations`
          ? saved.body
          : {
              idempotency_key: crypto.randomUUID(),
              channel,
              title:
                channel === "ask" ? "Ask conversation" : "Teach conversation",
            };
      identity.current = { path: `${base}/conversations`, body };
      const c = await requestApi<Conversation>(`${base}/conversations`, body);
      identity.current = null;
      select(c.id);
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const pending = detail?.work.some((w) =>
    [
      "queued",
      "awaiting_provider",
      "awaiting_local",
      "awaiting_narration",
    ].includes(w.status),
  );
  const question = detail?.questions[0];
  const proposal = detail?.proposals[0];
  const teachingClosed =
    channel === "teach" &&
    !!detail?.tasks.length &&
    (!!detail.tasks.at(-1)!.execution ||
      !["preparing", "needs_input"].includes(detail.tasks.at(-1)!.status)) &&
    !question;
  const staleQuestion =
    question &&
    (question.expires_at_ms <= Date.now() ||
      !sameContext(question.context, detail?.context));
  const interactionBlocked =
    question?.kind !== "budget" && !!detail?.readiness_issues?.length;
  const send = () => {
    if (
      !detail ||
      !text.trim() ||
      outbox ||
      pending ||
      proposal ||
      staleQuestion ||
      teachingClosed ||
      interactionBlocked ||
      uploading ||
      (attachments.length > 0 && !discloseFiles)
    )
      return;
    void submit(`${base}/conversations/${detail.id}/messages`, {
      idempotency_key: crypto.randomUUID(),
      channel,
      context: detail.context,
      text,
      attachment_ids: attachments.map((a) => a.id),
      disclose_attachments: discloseFiles,
      reply_to: question?.id || null,
    });
  };
  return (
    <section
      className="chat-workspace"
      aria-label={`${channel === "ask" ? "Ask" : "Teach"} workspace`}
    >
      <aside className="chat-history" aria-label={`${channel} conversations`}>
        <button
          className="primary"
          disabled={busy || adm.archived}
          onClick={() => void create()}
        >
          New {channel === "ask" ? "Ask" : "Teach"} conversation
        </button>
        <p className="muted">
          {channel === "ask"
            ? "Questions and requests"
            : "Teaching intentions and material"}{" "}
          · separate history
        </p>
        {[...conversations].reverse().map((c) => (
          <button
            key={c.id}
            className="chat-history-item"
            aria-current={c.id === conversationId ? "page" : undefined}
            onClick={() => select(c.id)}
          >
            {c.title}
            <small>{new Date(c.created_at_ms).toLocaleString()}</small>
          </button>
        ))}
      </aside>
      <div className="chat-main">
        {error && <Notice error>{error}</Notice>}
        {readError && <Notice error>{readError}</Notice>}
        {!detail ? (
          <div className="panel empty">
            <h2>
              {channel === "ask" ? "Ask your model" : "Help your model learn"}
            </h2>
            <p>
              Start a conversation or reopen one from this channel. Messages
              stay with this model.
            </p>
            <p className="muted">
              {channel === "ask"
                ? "Ask uses your configured provider to interpret questions. Supported requests run locally, with an optional AI explanation of the saved outcome."
                : "Describe a capability, supplied facts or a correction. Review its scope, then start bounded teaching and receive the outcome here."}{" "}
              Local debug remains available without a provider.
            </p>
          </div>
        ) : (
          <>
            <header className="chat-toolbar">
              <div>
                <strong>{detail.title}</strong>
                <p className="muted" role="status" aria-live="polite">
                  {detail.tasks.at(-1)?.execution
                    ? `Teaching · ${detail.tasks.at(-1)!.status.replaceAll("_", " ")}`
                    : workLabel(detail.work[0])}{" "}
                  ·{" "}
                  {detail.readiness === "needs_setup"
                    ? "Interaction setup needed"
                    : detail.readiness === "ready_for_ask"
                      ? "Ask configured"
                      : detail.readiness === "ready_for_teaching"
                        ? "Teaching allowance configured"
                        : "Clarification configured"}
                </p>
              </div>
              <div className="actions">
                <button
                  className="secondary"
                  disabled={busy || pending || !!proposal}
                  onClick={async () => {
                    try {
                      const value = await requestApi<{
                        items: Option[];
                        spending_enabled: boolean;
                        issues: ReadinessIssue[];
                      }>(
                        `${base}/interaction-options?purpose=${channel === "ask" ? "ask" : "teach"}`,
                      );
                      setOptions(value.items);
                      setSpending(value.spending_enabled);
                      setOptionIssues(value.issues || []);
                    } catch (e) {
                      setError((e as Error).message);
                    }
                  }}
                >
                  {channel === "ask"
                    ? "Set up interaction"
                    : "Set up teaching task"}
                </button>
                <button
                  className="secondary"
                  onClick={async () => {
                    setShowDetails(!showDetails);
                    if (!showDetails) {
                      try {
                        setTechnical(
                          await requestApi(
                            `${base}/conversations/${detail.id}/details`,
                          ),
                        );
                      } catch (e) {
                        setError((e as Error).message);
                      }
                    }
                  }}
                >
                  {showDetails ? "Hide details" : "Details"}
                </button>
              </div>
            </header>
            {showDetails && (
              <section
                className="panel"
                ref={detailsPanel}
                tabIndex={-1}
                aria-label="Saved technical details"
              >
                <h3>Saved technical details</h3>
                <p>
                  Exact contexts, decisions, work identities and provider
                  accounting. Interpretation history is available in Local
                  debug.
                </p>
                <pre className="chat-details">
                  {technical ? JSON.stringify(technical, null, 2) : "Loading…"}
                </pre>
                <button
                  onClick={() => {
                    setShowDetails(false);
                    composer.current?.focus();
                  }}
                >
                  Return to conversation
                </button>
              </section>
            )}
            {options && (
              <section className="panel">
                <h3>
                  Choose a provider for{" "}
                  {channel === "ask" ? "Ask" : "teaching preparation"}
                </h3>
                <p>
                  This local setup exchange makes no LLM call. The next step
                  asks for a USD cap and then your confirmation.
                </p>
                {!spending && (
                  <Notice>
                    Installation spending is disabled. Configure priced limits
                    in{" "}
                    <a href="#view=connections">
                      Connections → Installation spending
                    </a>{" "}
                    before authorizing paid interaction.
                  </Notice>
                )}
                {!options.length && (
                  <Notice>
                    {optionIssues.map((issue) => (
                      <p key={issue.code}>{issue.message}</p>
                    ))}
                    <a href="#view=connections">Review Connections</a>
                  </Notice>
                )}
                {options.map((o) => (
                  <div className="panel" key={o.price_id}>
                    <p>
                      {o.name} · {o.model}
                      {o.synthetic ? " · recorded test" : ""}
                    </p>
                    {channel === "teach" && (
                      <label>
                        <input
                          type="checkbox"
                          checked={queueSetup}
                          onChange={(e) => setQueueSetup(e.target.checked)}
                        />{" "}
                        Set up bounded ongoing source intake (up to 24 hours, no
                        automatic refill)
                      </label>
                    )}
                    <div className="actions">
                      {(channel === "ask" && o.can_narrate
                        ? [true, false]
                        : [false]
                      ).map((narrate) => (
                        <button
                          key={String(narrate)}
                          className="secondary"
                          disabled={busy || !spending}
                          onClick={() =>
                            void submit(
                              `${base}/conversations/${detail.id}/setup`,
                              {
                                idempotency_key: crypto.randomUUID(),
                                context: detail.context,
                                price_id: o.price_id,
                                purpose: channel === "ask" ? "ask" : "teach",
                                narrate_results: narrate,
                                source_queue: channel === "teach" && queueSetup,
                              },
                            )
                          }
                        >
                          {channel !== "ask"
                            ? "Use for teaching preparation"
                            : narrate
                              ? "Use for Ask and explanations"
                              : "Use for Ask only"}
                        </button>
                      ))}
                    </div>
                    {channel === "ask" && (
                      <p className="muted">
                        Ask shares your question, selected owner turns and
                        accepted catalog and historical metadata from source
                        configuration and snapshots. Explanations additionally
                        share the bounded result and scope, without source text.
                        Supported read-only requests run automatically on this
                        model.
                      </p>
                    )}
                  </div>
                ))}
              </section>
            )}
            <div
              className="chat-messages"
              role="log"
              aria-label={`${channel} messages`}
              aria-live="polite"
              aria-relevant="additions"
            >
              {detail.items.map((t) => (
                <article key={t.id} className={`chat-message ${t.author}`}>
                  <div className="chat-author">
                    {t.author === "owner"
                      ? "You"
                      : t.author === "assistant"
                        ? "Assistant · clarification"
                        : "Workspace"}
                  </div>
                  <RichText text={t.text} />
                  {detail.presentations
                    .filter((p) => p.turn_id === t.id)
                    .map((p) => (
                      <section key={p.id} className="chat-explanation">
                        {p.explanation ? (
                          <>
                            <strong>
                              AI explanation · not a checked result
                            </strong>
                            <RichText text={p.explanation} />
                          </>
                        ) : (
                          <p className="muted">
                            Showing the local outcome.{" "}
                            {p.fallback_reason === "disclosure_disabled"
                              ? "Result explanation was not authorized."
                              : "Provider explanation was unavailable; the saved outcome is preserved."}
                          </p>
                        )}
                        <button
                          className="secondary"
                          onClick={async () => {
                            try {
                              setTechnical(
                                await requestApi(
                                  `${base}/presentations/${p.id}`,
                                ),
                              );
                              setShowDetails(true);
                            } catch (e) {
                              setError((e as Error).message);
                            }
                          }}
                        >
                          Outcome details
                        </button>
                      </section>
                    ))}
                  {!!t.attachment_ids.length && (
                    <small>
                      {t.attachment_ids.length} attached material reference(s) ·
                      disclosure and provenance in Details
                    </small>
                  )}
                </article>
              ))}
            </div>
            {channel === "ask" &&
              detail.work
                .filter(
                  (w) =>
                    w.status === "needs_learning" ||
                    w.local_status === "needs_input",
                )
                .slice(0, 1)
                .map((w) => (
                  <section className="panel" key={w.id}>
                    <p>
                      This request needs model knowledge or additional input.
                      You can preserve it in Teach for follow-up. Teach can
                      prepare a checked specification after separate setup; this
                      link starts no learning or spending.
                    </p>
                    <button
                      disabled={busy || pending || !!outbox}
                      onClick={() =>
                        void submit(`${base}/ask/${w.id}/teach`, {
                          idempotency_key: `gap-${w.id}`,
                          context: detail.context,
                        })
                      }
                    >
                      Continue in Teach
                    </button>
                  </section>
                ))}
            {channel === "teach" &&
              detail.tasks.map((t) => (
                <TeachingTask
                  key={t.id}
                  task={t}
                  context={detail.context}
                  disabled={!!busy || !!outbox || !!adm.archived}
                  act={(id, body) =>
                    void submit(`${base}/tasks/${id}/commands`, body)
                  }
                  renew={(id, body) =>
                    void submit(`${base}/tasks/${id}/renewal`, body)
                  }
                />
              ))}
            {proposal && (
              <section
                className="chat-decision"
                aria-label={
                  proposal.kind === "task"
                    ? "Review teaching specification"
                    : "Confirm allowance"
                }
              >
                {proposal.kind === "task" && proposal.payload.specification ? (
                  <TeachingReview spec={proposal.payload.specification} />
                ) : (
                  <>
                    <h3>
                      {proposal.payload.purpose === "teach"
                        ? "Authorize this teaching allowance?"
                        : "Authorize this conversation’s interaction?"}
                    </h3>
                    <p>
                      <strong>{dollars(proposal.payload.cap_micro_usd)}</strong>{" "}
                      total cap · {proposal.payload.connection_name} ·{" "}
                      {proposal.payload.model}
                    </p>
                    <p>
                      Up to {proposal.payload.max_calls} calls. Expires{" "}
                      {new Date(
                        proposal.payload.expires_at_ms,
                      ).toLocaleTimeString()}
                      . No automatic refill.
                    </p>
                    <details>
                      <summary>Technical limits</summary>
                      <p>
                        {proposal.payload.max_input_tokens.toLocaleString()}{" "}
                        reserved input tokens and{" "}
                        {proposal.payload.max_output_tokens.toLocaleString()}{" "}
                        output tokens in total. Each call reserves up to{" "}
                        {(
                          proposal.payload.call_input_bound ?? 32000
                        ).toLocaleString()}{" "}
                        input tokens and allows{" "}
                        {proposal.payload.purpose === "teach"
                          ? "8,192"
                          : "4,096"}{" "}
                        output tokens and 60 seconds.
                      </p>
                    </details>
                    <p>Provider disclosure: {proposal.payload.disclosure}.</p>
                    <p>
                      {proposal.payload.purpose === "teach"
                        ? "Preparation and learning share this task cap; Ask is separate. Completion has reserved capacity. Review the prepared meaning before authorizing execution or source permissions."
                        : "The disclosure and operations above are the exact scope of this allowance. Learning acquisition has its own allowance and is not enabled by this decision."}
                    </p>
                  </>
                )}
                <div className="actions">
                  {(["accept", "decline"] as const).map((answer) => (
                    <button
                      key={answer}
                      className={answer === "accept" ? "primary" : "secondary"}
                      disabled={
                        busy || !!outbox || proposal.expires_at_ms <= Date.now()
                      }
                      onClick={() =>
                        void submit(`${base}/decisions/${proposal.id}`, {
                          idempotency_key: crypto.randomUUID(),
                          proposal_id: proposal.id,
                          proposal_digest: proposal.payload_digest,
                          context: proposal.context,
                          answer,
                        })
                      }
                    >
                      {answer === "accept"
                        ? proposal.kind === "task"
                          ? "Save teaching specification"
                          : "Confirm allowance"
                        : "Decline"}
                    </button>
                  ))}
                </div>
                {proposal.expires_at_ms <= Date.now() && (
                  <p>
                    This proposal expired. Start a new conversation to set up
                    fresh authority.
                  </p>
                )}
              </section>
            )}
            {outbox && (
              <Notice>
                This submission is retained for recovery. Review the error and
                saved history before retrying the exact same identity.
                <div className="actions">
                  <button
                    disabled={busy}
                    onClick={() => void submit(outbox.path, outbox.body)}
                  >
                    Recover submission
                  </button>
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() => {
                      sessionStorage.removeItem(storageKey);
                      setOutbox(null);
                    }}
                  >
                    Dismiss local retry
                  </button>
                </div>
              </Notice>
            )}
            {!!detail.stale_proposal_count && (
              <Notice>
                A previous decision expired or the model changed. Start
                interaction setup again to review current authority.
              </Notice>
            )}
            {staleQuestion && (
              <Notice>
                This question expired or the model context changed. Start a new
                conversation or repeat interaction setup; this reply cannot
                authorize work.
              </Notice>
            )}
            {teachingClosed && !proposal && (
              <p className="muted">
                Set up a new teaching task to prepare another objective. This
                task and its accounting remain saved.
              </p>
            )}
            {interactionBlocked && (
              <Notice>
                {detail.readiness_issues?.map((issue) => (
                  <p key={issue.code}>{issue.message}</p>
                ))}
                <p>
                  Your draft and saved results are retained. Sending does not
                  resume automatically.
                </p>
                {detail.readiness_issues?.some(
                  (issue) => issue.action === "connections",
                ) && <a href="#view=connections">Review Connections</a>}
                {detail.readiness_issues?.some(
                  (issue) => issue.action === "setup",
                ) && (
                  <p>
                    Use the setup button above to review a new allowance when
                    ready.
                  </p>
                )}
              </Notice>
            )}
            <form
              className="chat-composer"
              onSubmit={(e) => {
                e.preventDefault();
                send();
              }}
            >
              <label htmlFor="chat-text">
                {question
                  ? "Reply to the question above"
                  : channel === "ask"
                    ? "Message your model"
                    : "Describe what you want to teach"}
              </label>
              <textarea
                ref={composer}
                id="chat-text"
                rows={3}
                value={text}
                maxLength={16384}
                disabled={
                  busy ||
                  !!pending ||
                  !!proposal ||
                  !!outbox ||
                  !!staleQuestion ||
                  teachingClosed ||
                  adm.archived
                }
                onChange={(e) => editText(e.target.value)}
                onKeyDown={(e) => {
                  if (
                    e.key === "Enter" &&
                    !e.shiftKey &&
                    !e.nativeEvent.isComposing
                  ) {
                    e.preventDefault();
                    send();
                  }
                }}
                placeholder={question ? "Your reply…" : "Write a message…"}
              />
              {channel === "teach" && (
                <div>
                  <label>
                    Attach material (.md, .txt, .json or .jsonl)
                    <input
                      type="file"
                      accept=".md,.txt,.json,.jsonl"
                      multiple
                      disabled={
                        busy ||
                        uploading ||
                        !!pending ||
                        !!proposal ||
                        teachingClosed ||
                        adm.archived
                      }
                      onChange={async (e) => {
                        const scope = uploadScope.current;
                        const files = Array.from(e.target.files || []);
                        e.target.value = "";
                        if (files.length + attachments.length > 4) {
                          setError("Attach at most four files to one message.");
                          return;
                        }
                        setUploading(true);
                        setError("");
                        try {
                          const old = await requestApi<{
                            items: {
                              name: string;
                              source_id: string;
                              item_id: string;
                              current_source_version: string | null;
                            }[];
                          }>(`${base}/attachments`);
                          for (const file of files) {
                            if (file.size > 262144)
                              throw Error("Each attachment must fit 256 KiB.");
                            const content = new TextDecoder("utf-8", {
                              fatal: true,
                              ignoreBOM: true,
                            }).decode(await file.arrayBuffer());
                            const existing = old.items.find(
                              (a) =>
                                a.name === file.name &&
                                a.current_source_version,
                            );
                            const ext = file.name
                              .split(".")
                              .at(-1)
                              ?.toLowerCase();
                            if (
                              !["md", "txt", "json", "jsonl"].includes(
                                ext || "",
                              )
                            )
                              throw Error(
                                "Use .md, .txt, .json or .jsonl material.",
                              );
                            const uploaded = await requestApi<{
                              id: string;
                              name: string;
                              byte_count: number;
                              supersedes_version?: string;
                            }>(`${base}/attachments`, {
                              idempotency_key: crypto.randomUUID(),
                              name: file.name,
                              media_type:
                                ext === "md"
                                  ? "text/markdown"
                                  : ext === "json"
                                    ? "application/json"
                                    : ext === "jsonl"
                                      ? "application/x-ndjson"
                                      : "text/plain",
                              content,
                              ...(existing
                                ? {
                                    source_id: existing.source_id,
                                    item_id: existing.item_id,
                                    supersedes_version:
                                      existing.current_source_version,
                                  }
                                : {}),
                            });
                            if (scope !== uploadScope.current) return;
                            setAttachments((current) =>
                              current.some((a) => a.id === uploaded.id)
                                ? current
                                : [...current, uploaded],
                            );
                          }
                        } catch (err) {
                          setError((err as Error).message);
                        } finally {
                          setUploading(false);
                        }
                      }}
                    />
                  </label>
                  <button
                    type="button"
                    className="secondary"
                    disabled={
                      busy ||
                      uploading ||
                      !!pending ||
                      !!proposal ||
                      teachingClosed ||
                      adm.archived
                    }
                    onClick={async () => {
                      const scope = uploadScope.current;
                      try {
                        const value = await requestApi<{ items: Material[] }>(
                          `${base}/attachments`,
                        );
                        if (scope === uploadScope.current)
                          setRetained(value.items);
                      } catch (err) {
                        setError((err as Error).message);
                      }
                    }}
                  >
                    Choose retained material
                  </button>
                  {retained && (
                    <div aria-label="Retained material">
                      <p>
                        Files already stored in this model. Selection does not
                        share or teach them.
                      </p>
                      {retained.length === 0 && (
                        <p>No uploaded material yet.</p>
                      )}
                      {retained.map((a) => (
                        <button
                          key={a.id}
                          type="button"
                          className="secondary"
                          disabled={
                            attachments.length >= 4 ||
                            attachments.some((b) => b.id === a.id)
                          }
                          onClick={() => {
                            setAttachments((current) => [...current, a]);
                            setRetained(null);
                            setDiscloseFiles(false);
                          }}
                        >
                          {a.name} · {a.byte_count} bytes
                          {a.current_source_version &&
                          a.current_source_version !== a.version_id
                            ? " · older version"
                            : ""}
                        </button>
                      ))}
                      <button
                        type="button"
                        className="secondary"
                        onClick={() => setRetained(null)}
                      >
                        Close file list
                      </button>
                    </div>
                  )}
                  {!!attachments.length && (
                    <>
                      <ul>
                        {attachments.map((a) => (
                          <li key={a.id}>
                            {a.name} · {a.byte_count} bytes{" "}
                            {a.supersedes_version &&
                              "· correction of earlier material"}
                            <button
                              type="button"
                              className="secondary"
                              onClick={() =>
                                setAttachments((items) =>
                                  items.filter((i) => i.id !== a.id),
                                )
                              }
                            >
                              Remove from message
                            </button>
                          </li>
                        ))}
                      </ul>
                      <label>
                        <input
                          type="checkbox"
                          checked={discloseFiles}
                          onChange={(e) => setDiscloseFiles(e.target.checked)}
                        />{" "}
                        Include these files’ original content in this funded
                        teaching preparation. Upload alone does not share or
                        teach it.
                      </label>
                    </>
                  )}
                </div>
              )}
              <div className="chat-composer-footer">
                <small>
                  Enter to send · Shift+Enter for a new line. Original material
                  is retained locally.
                </small>
                <button
                  className="primary"
                  disabled={
                    busy ||
                    !!pending ||
                    !!proposal ||
                    !!outbox ||
                    !!staleQuestion ||
                    teachingClosed ||
                    interactionBlocked ||
                    !text.trim() ||
                    uploading ||
                    (attachments.length > 0 && !discloseFiles) ||
                    adm.archived
                  }
                >
                  Send
                </button>
              </div>
            </form>
          </>
        )}
      </div>
    </section>
  );
}

function TeachingReview({ spec }: { spec: TeachingSpec }) {
  return (
    <>
      <h3>Save this teaching specification?</h3>
      <p>
        <strong>Requested:</strong> {spec.objective}
      </p>
      <p>{spec.plan.summary}</p>
      <p>
        Total task cap: <strong>{dollars(spec.budget.cap_micro_usd)}</strong>,
        including preparation already performed. No automatic refill.
      </p>
      {spec.plan.children.map((c, i) => (
        <section className="panel" key={i}>
          <strong>
            {c.kind === "facts"
              ? "Supplied facts"
              : c.kind === "correction"
                ? "Correction"
                : "New capability"}
          </strong>
          <p>{c.objective}</p>
          <ul>
            {spec.interface_review[i].map((line, j) => (
              <li key={j}>{line}</li>
            ))}
          </ul>
          {c.material && (
            <>
              <p>Coverage: {c.material.projection.entities.join(", ")}</p>
              <ul>
                {c.material.projection.predicates.map((p) => (
                  <li key={p.symbol}>
                    {p.symbol}:{" "}
                    {p.kind === "integer"
                      ? `${p.minimum}–${p.maximum}`
                      : p.kind === "enum"
                        ? p.values.join(", ")
                        : "true or false"}{" "}
                    · {p.unit}
                  </li>
                ))}
              </ul>
              <ul>
                {c.material.projection.cells.map((cell, j) => (
                  <li key={j}>
                    {cell.effective_from}{" "}
                    {cell.effective_to
                      ? `until ${cell.effective_to} (exclusive)`
                      : "(point in time)"}{" "}
                    · {cell.granularity}
                  </li>
                ))}
              </ul>
              <p>
                Attribution:{" "}
                {c.material.sources.map((s) => s.attribution).join("; ")}.
                External source disclosure is off.
              </p>
            </>
          )}
        </section>
      ))}
      <p>
        {spec.plan.requirements
          ? "Additional acceptance checks are proposed. They are not independent evidence and require separate owner review before installation."
          : "Existing owner acceptance requirements remain binding; no new checks are proposed."}
      </p>
      <p>
        This approves preparation only. Requirements, source permissions and
        vocabulary remain uninstalled; learning has not started. Execution
        requires a separate Start teaching decision. Exact interfaces and
        proposed checks are available in Details.
      </p>
    </>
  );
}
