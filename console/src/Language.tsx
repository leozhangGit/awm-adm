import { useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { providerBlock, submissionError } from "./feedback.ts";
import type { ProviderFailureView } from "./feedback.ts";
import { ProviderFailure } from "./ProviderFailure.tsx";
import { HistoricalLookup } from "./HistoricalLookup.tsx";
import {
  Badge,
  JsonDetail,
  JsonEditor,
  Notice,
  ResultPanel,
} from "./components.tsx";
import { intentLines, suggestions } from "./language.ts";
import { parseJson } from "./query.ts";
import type { Adm, Json, Limits, Model, RequestView } from "./types.ts";
import { pretty, short } from "./types.ts";

type TurnSummary = {
  id: string;
  utterance: string;
  status: string;
  translator: string;
};
type Teaching = { id: string; text: string; status: string };
type Conversation = {
  id: string;
  title: string;
  interpretations: TurnSummary[];
  teaching_drafts: Teaching[];
};
type Interpretation = {
  id: string;
  status: string;
  revision_id: string;
  stale: boolean;
  body: { utterance: string; translator: string };
  draft: null | {
    query: Record<string, Json> | null;
    catalog_digest: string;
    translator: string;
    assumptions: string[];
    clarification: string | null;
  };
  choices: string[];
  error: string | null;
  revalidation?: { source_translator: string } | null;
  request?: RequestView;
  usage: unknown;
  provenance?: unknown;
  provider_failure?: ProviderFailureView | null;
};
type Connection = {
  id: string;
  name: string;
  provider: string;
  model: string;
  version: number;
  enabled: boolean;
  status: string;
  purposes: string[];
};
type Vocabulary = { generation: number; vocabulary: Json };
const pending = (s: string) =>
  ["queued", "checking", "awaiting_provider"].includes(s);

export function Language({
  adm,
  model,
  limits,
  onTeach,
  onHistory,
}: {
  adm: Adm;
  model: Model;
  limits: Limits;
  onTeach: (draft: Teaching) => void;
  onHistory: (request: string) => void;
}) {
  const base = `/adms/${adm.id}`;
  const [conversations, setConversations] = useState<
      { id: string; title: string }[]
    >([]),
    [conversation, setConversation] = useState(""),
    [history, setHistory] = useState<Conversation | null>(null),
    [selected, setSelected] = useState(""),
    [detail, setDetail] = useState<Interpretation | null>(null),
    [text, setText] = useState(""),
    [mode, setMode] = useState("ask"),
    [translator, setTranslator] = useState("local"),
    [connections, setConnections] = useState<Connection[]>([]),
    [providerSettings, setProviderSettings] = useState<{
      remote_calls_enabled: boolean;
    } | null>(null),
    [connection, setConnection] = useState(""),
    [disclose, setDisclose] = useState(false),
    [context, setContext] = useState<string[]>([]),
    [callLimits, setCallLimits] = useState('{"max_output_tokens":2048}'),
    [vocabulary, setVocabulary] = useState<Vocabulary | null>(null),
    [rawVocabulary, setRawVocabulary] = useState(""),
    [error, setError] = useState(""),
    [providerError, setProviderError] = useState(""),
    [readError, setReadError] = useState(""),
    [busy, setBusy] = useState(false);
  const intent = useRef<{ meaning: string; key: string } | null>(null);
  const seq = useRef(0);
  useEffect(() => {
    let current = true;
    async function load() {
      try {
        const page = await api<{ items: { id: string; title: string }[] }>(
          `${base}/interpretation-sessions`,
        );
        if (current) {
          setConversations(page.items);
          setReadError("");
        }
      } catch (e) {
        if (current) setReadError((e as Error).message);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [base]);
  useEffect(() => {
    let current = true;
    setHistory(null);
    setDetail(null);
    async function load() {
      try {
        const [h, d] = await Promise.all([
          conversation
            ? api<Conversation>(
                `${base}/interpretation-sessions/${conversation}`,
              )
            : Promise.resolve(null),
          selected
            ? api<Interpretation>(`${base}/interpretations/${selected}`)
            : Promise.resolve(null),
        ]);
        if (current) {
          setHistory(h);
          setDetail(d);
          setReadError("");
        }
      } catch (e) {
        if (current) setReadError((e as Error).message);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 1200);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [base, conversation, selected, model.revision_id]);
  useEffect(() => {
    if (translator !== "external") return;
    let current = true;
    async function loadProvider() {
      try {
        const [c, settings] = await Promise.all([
          api<{ items: Connection[] }>("/connections"),
          api<{ remote_calls_enabled: boolean }>("/learning"),
        ]);
        if (current) {
          setConnections(c.items);
          setProviderSettings(settings);
          setProviderError("");
        }
      } catch (e) {
        if (current) {
          setProviderSettings(null);
          setProviderError((e as Error).message);
        }
      }
    }
    void loadProvider();
    const timer = setInterval(() => void loadProvider(), 3000);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [translator]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    const token = ++seq.current;
    try {
      await action();
    } catch (e) {
      if (token === seq.current) setError(submissionError(e));
    } finally {
      if (token === seq.current) setBusy(false);
    }
  }
  async function post<T>(
    path: string,
    body: Record<string, unknown>,
  ): Promise<T> {
    const meaning = JSON.stringify({ path, body });
    if (intent.current?.meaning !== meaning)
      intent.current = { meaning, key: crypto.randomUUID() };
    const value = await api<T>(path, {
      method: "POST",
      body: { ...body, idempotency_key: intent.current.key },
    });
    intent.current = null;
    return value;
  }
  async function createConversation() {
    const c = await post<{ id: string; title: string }>(
      `${base}/interpretation-sessions`,
      { title: `Interpretation session ${conversations.length + 1}` },
    );
    setConversations((prev) => [c, ...prev.filter((x) => x.id !== c.id)]);
    setConversation(c.id);
    setSelected("");
    setContext([]);
    setText("");
  }
  async function ask(clarify = false) {
    const c = connections.find((x) => x.id === connection);
    const blocked = providerBlock(c, providerSettings, "interpretation");
    if (translator === "external" && blocked) throw Error(blocked);
    if (translator === "external" && (!c || !disclose))
      throw Error(
        "Select an enabled interpretation connection and approve the disclosure.",
      );
    const body = {
      expected_revision: model.revision_id,
      conversation_id: conversation,
      utterance: text,
      translator,
      ...(translator === "external"
        ? {
            connection_id: c!.id,
            connection_version: c!.version,
            disclose_catalog: disclose,
            context_turn_ids: context,
            call_limits: parseJson(callLimits),
          }
        : {}),
    };
    const value = await post<Interpretation>(
      `${base}/interpretations${clarify ? `/${selected}/clarify` : ""}`,
      body,
    );
    setSelected(value.id);
    setDetail(value);
    setDisclose(false);
  }
  const blockedProvider = providerBlock(
    connections.find((c) => c.id === connection),
    providerSettings,
    "interpretation",
  );
  const query = detail?.draft?.query;
  const remote =
    detail?.draft?.translator === "external" ||
    detail?.revalidation?.source_translator === "external";
  return (
    <>
      <section className="panel language-panel" aria-label="Ask and Teach">
        <div className="section-title">
          <div>
            <p className="eyebrow">WORDS TO LOCAL REQUESTS</p>
            <h2>Ask your ADM</h2>
          </div>
          <Badge tone="blue">Review before execution</Badge>
        </div>
        <p className="muted">
          Use the local phrases below, or explicitly select a provider to
          interpret broader wording. Answers always come from the accepted local
          model.
        </p>
        <div className="buttons">
          <label>
            Interpretation session
            <select
              aria-label="Interpretation session"
              value={conversation}
              disabled={busy}
              onChange={(e) => {
                setConversation(e.target.value);
                setSelected("");
                setContext([]);
                setText("");
              }}
            >
              <option value="">Select an interpretation session</option>
              {conversations.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.title}
                </option>
              ))}
            </select>
          </label>
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void run(createConversation)}
          >
            New interpretation session
          </button>
        </div>
        {readError && <Notice error>{readError}</Notice>}
        {error && <Notice error>{error}</Notice>}
        {conversation && (
          <>
            <div className="segmented" aria-label="Interaction intent">
              <button
                aria-pressed={mode === "ask"}
                onClick={() => setMode("ask")}
              >
                Ask
              </button>
              <button
                aria-pressed={mode === "teach"}
                onClick={() => setMode("teach")}
              >
                Teach
              </button>
            </div>
            {mode === "ask" ? (
              <>
                <label>
                  Interpretation
                  <select
                    aria-label="Interpretation"
                    value={translator}
                    onChange={(e) => {
                      setTranslator(e.target.value);
                      setDisclose(false);
                    }}
                  >
                    <option value="local">
                      Local · offline bounded language
                    </option>
                    <option value="external">
                      Provider assisted · one separately budgeted call
                    </option>
                  </select>
                </label>
                <details>
                  <summary>Local phrases from this model</summary>
                  <p>
                    These are editable templates. Check all arguments and the
                    initial state before interpreting.
                  </p>
                  <div className="language-suggestions">
                    {suggestions(model.declarations).map((p) => (
                      <button
                        className="secondary"
                        key={p}
                        onClick={() => setText(p)}
                      >
                        {p}
                      </button>
                    ))}
                  </div>
                  <p className="muted">
                    Also: “is FUNCTION with JSON?”, “check MODULE claim JSON”,
                    “explain RESULT_ID”. Plans accept “using [action names]” and
                    “within N steps”. Dates, entities and units must match the
                    model; no implicit conversions.
                  </p>
                </details>
                {translator === "external" && (
                  <div className="language-disclosure">
                    {providerError && <Notice error>{providerError}</Notice>}
                    {providerSettings && (
                      <p className="muted">
                        Installation remote calls:{" "}
                        <strong>
                          {providerSettings.remote_calls_enabled
                            ? "allowed"
                            : "disabled"}
                        </strong>
                        . Connection readiness and disclosure consent are also
                        required.
                      </p>
                    )}
                    {blockedProvider && (
                      <Notice>
                        {blockedProvider}{" "}
                        <a href="#view=connections">Open Connections</a>
                      </Notice>
                    )}
                    {!blockedProvider && (
                      <p className="muted">
                        Selected connection is ready; this submission still
                        requires your disclosure consent and bounded call
                        limits.
                      </p>
                    )}
                    <label>
                      Interpretation connection
                      <select
                        value={connection}
                        onChange={(e) => {
                          setConnection(e.target.value);
                          setDisclose(false);
                        }}
                      >
                        <option value="">Choose a connection</option>
                        {connections
                          .filter(
                            (c) =>
                              c.enabled &&
                              c.purposes.includes("interpretation"),
                          )
                          .map((c) => (
                            <option key={c.id} value={c.id}>
                              {c.name} · {c.provider}/{c.model} · v{c.version}
                            </option>
                          ))}
                      </select>
                    </label>
                    <p>
                      Enable the interpretation purpose in Connections if none
                      are listed. Provider text proposes a request; it is not an
                      answer.
                    </p>
                    <JsonEditor
                      label="One-call limits"
                      value={callLimits}
                      onChange={setCallLimits}
                      rows={3}
                    />
                    <details>
                      <summary>
                        Choose prior user messages to disclose ({context.length}
                        /6)
                      </summary>
                      {history?.interpretations.map((t) => (
                        <label className="check" key={t.id}>
                          <input
                            type="checkbox"
                            checked={context.includes(t.id)}
                            disabled={
                              !context.includes(t.id) && context.length >= 6
                            }
                            onChange={(e) => {
                              setContext((v) =>
                                e.target.checked
                                  ? [...v, t.id]
                                  : v.filter((id) => id !== t.id),
                              );
                              setDisclose(false);
                            }}
                          />
                          {t.utterance}
                        </label>
                      ))}
                    </details>
                    <label className="check">
                      <input
                        type="checkbox"
                        checked={disclose}
                        onChange={(e) => setDisclose(e.target.checked)}
                      />
                      Send this question, accepted symbol/type catalog, owner
                      vocabulary and the selected user messages to this
                      connection. No assistant answers are included.
                    </label>
                  </div>
                )}
              </>
            ) : (
              <Notice>
                Teaching saves an untrusted proposal. You will separately review
                a learning task, interfaces, provider and budgets before any
                acquisition. This text does not change accepted knowledge.
              </Notice>
            )}
            <label htmlFor="language-text">
              {mode === "ask" ? "Your question" : "Proposed knowledge"}
            </label>
            <textarea
              id="language-text"
              value={text}
              maxLength={16384}
              rows={4}
              onChange={(e) => {
                setText(e.target.value);
                setDisclose(false);
              }}
              placeholder={
                mode === "ask"
                  ? "What can you do?"
                  : "Describe what you want this ADM to learn."
              }
            />
            <div className="buttons">
              <button
                className="primary"
                disabled={
                  busy ||
                  !text.trim() ||
                  (mode === "ask" &&
                    translator === "external" &&
                    (!disclose || !!blockedProvider))
                }
                onClick={() =>
                  void run(async () => {
                    if (mode === "ask") await ask();
                    else {
                      const d = await post<Teaching>(
                        `${base}/interpretation-sessions/${conversation}/teach`,
                        { expected_revision: model.revision_id, text },
                      );
                      setHistory(
                        await api<Conversation>(
                          `${base}/interpretation-sessions/${conversation}`,
                        ),
                      );
                      setText("");
                      setSelected("");
                      setDetail(null);
                      if (!d.id) throw Error("Missing draft identity");
                    }
                  })
                }
              >
                {busy
                  ? "Working…"
                  : mode === "ask"
                    ? "Interpret and preview"
                    : "Save teaching proposal"}
              </button>
              {mode === "ask" && detail && !pending(detail.status) && (
                <button
                  className="secondary"
                  disabled={
                    busy ||
                    !text.trim() ||
                    (translator === "external" && !disclose)
                  }
                  onClick={() => void run(() => ask(true))}
                >
                  Submit clarification
                </button>
              )}
            </div>
          </>
        )}
      </section>
      {history &&
        (history.interpretations.length > 0 ||
          history.teaching_drafts.length > 0) && (
          <section className="panel">
            <h3>Conversation history</h3>
            <div className="language-history">
              {history.interpretations.map((t) => (
                <button
                  className="secondary"
                  key={t.id}
                  aria-pressed={selected === t.id}
                  onClick={() => {
                    setSelected(t.id);
                    setText(t.utterance);
                    setMode("ask");
                    setDisclose(false);
                  }}
                >
                  <span>{t.utterance}</span>
                  <small>
                    {t.translator} · {t.status.replaceAll("_", " ")}
                  </small>
                </button>
              ))}
            </div>
            {history.teaching_drafts.map((t) => (
              <div className="teaching-draft" key={t.id}>
                <Badge>Teaching proposal · unaccepted</Badge>
                <p>{t.text}</p>
                <button className="secondary" onClick={() => onTeach(t)}>
                  Review learning task
                </button>
              </div>
            ))}
          </section>
        )}
      {detail && (
        <section className="panel" aria-label="Interpretation preview">
          <div className="section-title">
            <h2>
              {pending(detail.status)
                ? "Preparing interpretation…"
                : "Interpretation preview"}
            </h2>
            <Badge>{detail.status.replaceAll("_", " ")}</Badge>
          </div>
          <p>{detail.body.utterance}</p>
          <p className="muted">
            {remote
              ? "Provider-proposed interpretation, checked locally for types and catalog references. Review its meaning; type checking does not establish that it understood you."
              : "Interpreted by the bounded local language parser."}
          </p>
          <p>
            Model revision <code>{short(detail.revision_id)}</code>
          </p>
          {detail.stale && (
            <Notice>
              This preview uses an older model or vocabulary. Revalidate and
              review a new preview before execution.
            </Notice>
          )}
          <ProviderFailure failure={detail.provider_failure} />
          {detail.error && !detail.provider_failure && (
            <Notice error>{detail.error.replaceAll("_", " ")}</Notice>
          )}
          {detail.draft?.clarification && (
            <Notice>{detail.draft.clarification}</Notice>
          )}
          {detail.choices.length > 0 && (
            <p>
              Possible names: {detail.choices.join(", ")}. Supply a complete
              clarified question above.
            </p>
          )}
          {query && (
            <>
              <ul>
                {intentLines(query).map((s) => (
                  <li key={s}>{s}</li>
                ))}
              </ul>
              {detail.draft!.assumptions.length > 0 && (
                <>
                  <h3>Proposed assumptions</h3>
                  <ul>
                    {detail.draft!.assumptions.map((a, i) => (
                      <li key={i}>{a}</li>
                    ))}
                  </ul>
                </>
              )}
              <JsonDetail label="Exact typed request" value={query} />
              <p className="muted">
                Local budget: {limits.max_work.toLocaleString()} work units ·{" "}
                {limits.max_duration_ms / 1000}s ·{" "}
                {limits.max_states.toLocaleString()} states.
              </p>
              <div className="buttons">
                {!detail.request && (
                  <button
                    className="primary"
                    disabled={busy || detail.stale || detail.status !== "ready"}
                    onClick={() =>
                      void run(async () => {
                        await api(
                          `${base}/interpretations/${detail.id}/execute`,
                          {
                            method: "POST",
                            body: {
                              idempotency_key: `execute:${detail.id}`,
                              expected_revision: detail.revision_id,
                              expected_catalog_digest:
                                detail.draft!.catalog_digest,
                              limits,
                            },
                          },
                        );
                        setDetail(
                          await api<Interpretation>(
                            `${base}/interpretations/${detail.id}`,
                          ),
                        );
                      })
                    }
                  >
                    Confirm and run locally
                  </button>
                )}
                {detail.stale && (
                  <button
                    className="secondary"
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        const d = await post<Interpretation>(
                          `${base}/interpretations/${detail.id}/revalidate`,
                          { expected_revision: model.revision_id },
                        );
                        setSelected(d.id);
                        setDetail(d);
                      })
                    }
                  >
                    Revalidate locally
                  </button>
                )}
              </div>
            </>
          )}
          {(pending(detail.status) ||
            (detail.status === "ready" && !detail.request)) && (
            <button
              className="text-button"
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  setDetail(
                    await api<Interpretation>(
                      `${base}/interpretations/${detail.id}/cancel`,
                      { method: "POST" },
                    ),
                  );
                })
              }
            >
              Cancel interpretation
            </button>
          )}
          {detail.usage != null && (
            <JsonDetail
              label="Interpretation cost and reservation"
              value={detail.usage}
            />
          )}
          {detail.provenance != null && (
            <JsonDetail label="Provider provenance" value={detail.provenance} />
          )}
        </section>
      )}
      {detail?.request && (
        <>
          <ResultPanel
            request={detail.request}
            busy={busy}
            onCancel={() =>
              void run(async () => {
                await api(
                  `${base}/requests/${detail.request!.request_id}/cancel`,
                  { method: "POST" },
                );
                setDetail(
                  await api<Interpretation>(
                    `${base}/interpretations/${detail.id}`,
                  ),
                );
              })
            }
            onRetry={() =>
              void run(async () => {
                await api(
                  `${base}/requests/${detail.request!.request_id}/retry`,
                  { method: "POST" },
                );
                setDetail(
                  await api<Interpretation>(
                    `${base}/interpretations/${detail.id}`,
                  ),
                );
              })
            }
          />
          <button
            className="secondary"
            onClick={() => onHistory(detail.request!.request_id)}
          >
            Open request history and retry controls
          </button>
        </>
      )}
      <HistoricalLookup
        adm={adm.id}
        revision={model.revision_id}
        limits={limits}
        onHistory={onHistory}
      />
      <section className="panel">
        <details>
          <summary>
            Owner vocabulary · aliases, entities, units and time parameters
          </summary>
          <p>
            Metadata is checked against this model. Changing it makes existing
            previews stale. It does not modify accepted theory.
          </p>
          <button
            className="secondary"
            disabled={busy}
            onClick={() =>
              void run(async () => {
                const v = await api<Vocabulary>(`${base}/language/vocabulary`);
                setVocabulary(v);
                setRawVocabulary(pretty(v.vocabulary));
              })
            }
          >
            Load vocabulary settings
          </button>
          {vocabulary && (
            <>
              <JsonEditor
                label="Vocabulary JSON"
                value={rawVocabulary}
                onChange={setRawVocabulary}
                rows={10}
              />
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void run(async () => {
                    const v = await api<Vocabulary>(
                      `${base}/language/vocabulary`,
                      {
                        method: "PUT",
                        body: {
                          expected_revision: model.revision_id,
                          expected_generation: vocabulary.generation,
                          vocabulary: parseJson(rawVocabulary),
                        },
                      },
                    );
                    setVocabulary(v);
                    setRawVocabulary(pretty(v.vocabulary));
                  })
                }
              >
                Save vocabulary
              </button>
            </>
          )}
        </details>
      </section>
    </>
  );
}
