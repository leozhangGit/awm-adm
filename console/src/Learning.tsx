import { useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { Badge, JsonDetail, JsonEditor, Notice } from "./components.tsx";
import type { ProviderFailureView } from "./feedback.ts";
import { ProviderFailure } from "./ProviderFailure.tsx";
import { parseJson } from "./query.ts";
import type { Adm } from "./types.ts";
import { pretty, short } from "./types.ts";
import { Spending, ConnectionPricing } from "./Spending.tsx";

type Connection = {
  id: string;
  version: number;
  name: string;
  provider: string;
  model: string;
  enabled: boolean;
  status: string;
  purposes: string[];
  capabilities: string[];
  credential_mode: string;
  recorded_responses?: unknown[];
  recorded_response_count: number;
};
type Settings = {
  generation: number;
  remote_calls_enabled: boolean;
  gateway_key: { key_id: string; spki: string } | null;
  call_caps: Record<string, number>;
  episode_caps: Record<string, number>;
  usage: Record<string, number>;
  quotas: Record<string, number>;
};
type Receipt = {
  id: string;
  seq: number;
  status: string;
  data: Record<string, unknown>;
};
type Episode = {
  id: string;
  status: string;
  reason: string | null;
  work: number;
  no_progress: number;
  grant_id: string | null;
  deadline: number;
  receipts?: Receipt[];
  history?: Record<string, unknown>[];
  usage?: Record<string, number>;
  body?: Record<string, unknown>;
  provider_failure?: ProviderFailureView | null;
};
const terminal = (s: string) =>
  ["accepted", "stopped", "rejected", "cancelled"].includes(s);

export async function sealCredential(
  key: Settings["gateway_key"],
  credential: string,
  provider: string,
  idempotencyKey: string,
) {
  if (!key) throw Error("Wait for the credential gateway to become ready.");
  const spki = Uint8Array.from(atob(key.spki), (c) => c.charCodeAt(0));
  const publicKey = await crypto.subtle.importKey(
    "spki",
    spki,
    { name: "RSA-OAEP", hash: "SHA-256" },
    false,
    ["encrypt"],
  );
  const plaintext = new TextEncoder().encode(
    JSON.stringify({ credential, provider, idempotency_key: idempotencyKey }),
  );
  try {
    const result = await crypto.subtle.encrypt(
      {
        name: "RSA-OAEP",
        label: new TextEncoder().encode("awm-adm-provider-credential/1"),
      },
      publicKey,
      plaintext,
    );
    return {
      sealed_credential: btoa(String.fromCharCode(...new Uint8Array(result))),
      sealing_key_id: key.key_id,
    };
  } finally {
    plaintext.fill(0);
  }
}

export function Connections() {
  const testPanel = useRef<HTMLElement>(null);
  const [connections, setConnections] = useState<Connection[]>([]),
    [settings, setSettings] = useState<Settings | null>(null);
  const [selected, setSelected] = useState<Connection | null>(null),
    [name, setName] = useState(""),
    [provider, setProvider] = useState("recorded"),
    [model, setModel] = useState(""),
    [enabled, setEnabled] = useState(false),
    [purposes, setPurposes] = useState(["acquisition", "connection_test"]),
    [credentialMode, setCredentialMode] = useState("managed"),
    [secret, setSecret] = useState(""),
    [recorded, setRecorded] = useState("[]");
  const [error, setError] = useState(""),
    [readError, setReadError] = useState(""),
    [busy, setBusy] = useState(false),
    [message, setMessage] = useState(""),
    [test, setTest] = useState<Record<string, unknown> | null>(null),
    [testConnection, setTestConnection] = useState<Connection | null>(null),
    [testCaps, setTestCaps] = useState("{}");
  useEffect(() => {
    if (testConnection) {
      testPanel.current?.focus();
      testPanel.current?.scrollIntoView({ block: "start" });
    }
  }, [testConnection]);
  const saved = useRef<{
    meaning: string;
    body: Record<string, unknown>;
  } | null>(null);
  const testIntent = useRef<{ meaning: string; key: string } | null>(null);
  async function load() {
    try {
      const [c, s] = await Promise.all([
        api<{ items: Connection[] }>("/connections"),
        api<Settings>("/learning"),
      ]);
      setConnections(c.items);
      setSettings(s);
      setReadError("");
    } catch (e) {
      setReadError((e as Error).message);
    }
  }
  useEffect(() => {
    void load();
    const t = setInterval(() => void load(), 3000);
    return () => clearInterval(t);
  }, []);
  useEffect(() => {
    if (
      !test?.id ||
      !["ready", "leased", "dispatched"].includes(String(test.status))
    )
      return;
    const t = setInterval(
      () =>
        void api<Record<string, unknown>>(`/dispatches/${test.id}`)
          .then(setTest)
          .catch((e) => setReadError(e.message)),
      1000,
    );
    return () => clearInterval(t);
  }, [test]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await action();
      await load();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  function reset() {
    setSelected(null);
    setName("");
    setModel("");
    setSecret("");
    setRecorded("[]");
    setEnabled(false);
    setPurposes(["acquisition", "connection_test"]);
    saved.current = null;
  }
  async function edit(c: Connection) {
    const details = await api<Connection>(`/connections/${c.id}`);
    setSelected(c);
    setName(c.name);
    setProvider(c.provider);
    setModel(c.model);
    setEnabled(c.enabled);
    setPurposes(c.purposes);
    setCredentialMode(
      c.credential_mode === "none" ? "managed" : c.credential_mode,
    );
    setRecorded(pretty(details.recorded_responses || []));
    setSecret("");
    saved.current = null;
  }
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">KNOWLEDGE CONNECTIONS</p>
          <h1>Choose how your models learn.</h1>
          <p className="muted">
            Connections propose knowledge. Accepted models continue serving
            locally.
          </p>
        </div>
        <Badge tone={settings?.remote_calls_enabled ? "amber" : "green"}>
          {settings?.remote_calls_enabled
            ? "Remote calls enabled"
            : "Remote calls disabled"}
        </Badge>
      </div>
      {readError && (
        <Notice error>Could not refresh connections: {readError}</Notice>
      )}
      {error && <Notice error>{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      {settings && (
        <section className="panel">
          <div className="section-title">
            <div>
              <h2>Installation allowance</h2>
              <p>
                {settings.usage.calls} calls charged or reserved ·{" "}
                {settings.usage.unresolved} unresolved reservations
              </p>
            </div>
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await api("/learning", {
                    method: "PUT",
                    body: {
                      expected_generation: settings.generation,
                      remote_calls_enabled: !settings.remote_calls_enabled,
                    },
                  });
                  setMessage(
                    "Learning authority updated. In-flight outcomes keep their accounting.",
                  );
                })
              }
            >
              {settings.remote_calls_enabled
                ? "Disable remote calls"
                : "Enable remote calls"}
            </button>
          </div>
          <JsonDetail
            label="Token usage and configured quotas"
            value={{ usage: settings.usage, quotas: settings.quotas }}
          />
          <p className="muted">
            Recorded fixtures use no account. A remote connection test is a
            real, budgeted provider call.
          </p>
        </section>
      )}
      <div className="learning-grid">
        <section className="panel">
          <h2>Connections</h2>
          {!connections.length && (
            <p className="muted">
              Add a recorded fixture or configure a provider.
            </p>
          )}
          <div className="operation-list">
            {connections.map((c) => (
              <article key={c.id} className="connection-item">
                <div>
                  <strong>{c.name}</strong>
                  <p className="muted">
                    {c.provider} · {c.model} · version {c.version}
                  </p>
                  <Badge
                    tone={c.status === "ready" && c.enabled ? "green" : "amber"}
                  >
                    {c.enabled ? c.status : "Disabled"}
                  </Badge>
                </div>
                <div className="buttons">
                  <button
                    disabled={busy}
                    onClick={() => void run(() => edit(c))}
                  >
                    Configure
                  </button>
                  <ConnectionPricing key={`${c.id}:${c.version}`} id={c.id} />
                  <button
                    disabled={
                      busy ||
                      !c.enabled ||
                      c.status !== "ready" ||
                      !c.purposes.includes("connection_test")
                    }
                    onClick={() => {
                      setTestConnection(c);
                      setTestCaps(
                        pretty({
                          ...settings!.call_caps,
                          max_output_tokens: 64,
                        }),
                      );
                      setTest(null);
                    }}
                  >
                    Test…
                  </button>
                </div>
              </article>
            ))}
          </div>
        </section>
        <section className="panel">
          <div className="section-title">
            <h2>
              {selected ? `Configure ${selected.name}` : "Add a connection"}
            </h2>
            {selected && <button onClick={reset}>New connection</button>}
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              void run(async () => {
                const responses =
                  provider === "recorded" ? parseJson(recorded) : [];
                if (!Array.isArray(responses))
                  throw Error("Recorded replies must be a JSON array.");
                const meaning = JSON.stringify({
                  selected: selected?.id,
                  version: selected?.version,
                  name,
                  provider,
                  model,
                  enabled,
                  credentialMode,
                  purposes,
                  responses,
                  secret,
                });
                if (saved.current?.meaning !== meaning) {
                  const idempotency_key = crypto.randomUUID();
                  const sealed =
                    provider !== "recorded" &&
                    credentialMode === "managed" &&
                    secret
                      ? await sealCredential(
                          settings?.gateway_key || null,
                          secret,
                          provider,
                          idempotency_key,
                        )
                      : {};
                  saved.current = {
                    meaning,
                    body: {
                      idempotency_key,
                      name,
                      provider,
                      model,
                      enabled,
                      purposes,
                      capabilities: ["json_schema", "recursive_refs"],
                      credential_mode:
                        provider === "recorded" ? "none" : credentialMode,
                      recorded_responses: responses,
                      ...sealed,
                      ...(selected
                        ? { expected_version: selected.version }
                        : {}),
                    },
                  };
                }
                const result = await api<Connection>(
                  selected ? `/connections/${selected.id}` : "/connections",
                  {
                    method: selected ? "PUT" : "POST",
                    body: saved.current.body,
                  },
                );
                reset();
                setMessage(
                  `${result.name} saved as version ${result.version}. Waiting for gateway synchronization.`,
                );
              });
            }}
          >
            <label>
              Name
              <input
                required
                value={name}
                maxLength={128}
                onChange={(e) => setName(e.target.value)}
              />
            </label>
            <label>
              Provider
              <select
                value={provider}
                onChange={(e) => {
                  setProvider(e.target.value);
                  setSecret("");
                }}
              >
                <option value="recorded">Recorded fixture (offline)</option>
                <option value="openai">OpenAI</option>
                <option value="anthropic">Anthropic</option>
              </select>
            </label>
            <label>
              Model identifier
              <input
                required
                value={model}
                maxLength={200}
                placeholder={
                  provider === "recorded"
                    ? "authored-fixture"
                    : "Your configured model ID"
                }
                onChange={(e) => setModel(e.target.value)}
              />
            </label>
            {provider === "recorded" ? (
              <>
                <JsonEditor
                  label="Recorded structured replies (JSON array)"
                  value={recorded}
                  onChange={setRecorded}
                  rows={8}
                />
                <button
                  type="button"
                  onClick={() =>
                    void run(async () => {
                      const f = await fetch("/examples/learning-capacity.json");
                      if (!f.ok) throw Error("Example unavailable");
                      const data = parseJson(await f.text()) as {
                        replies: unknown;
                      };
                      setRecorded(pretty(data.replies));
                      if (!name) setName("[Sandbox] Capacity fixture");
                      if (!model) setModel("authored-capacity-fixture");
                    })
                  }
                >
                  Load authored capacity fixture
                </button>
              </>
            ) : (
              <>
                <label>
                  Credential storage
                  <select
                    value={credentialMode}
                    onChange={(e) => {
                      setCredentialMode(e.target.value);
                      setSecret("");
                    }}
                  >
                    <option value="managed">Encrypted gateway storage</option>
                    <option value="static">Mounted provider secret</option>
                  </select>
                </label>
                {credentialMode === "managed" ? (
                  <label>
                    {selected
                      ? "New API key (leave blank to retain)"
                      : "API key"}
                    <input
                      type="password"
                      autoComplete="new-password"
                      maxLength={256}
                      value={secret}
                      onChange={(e) => setSecret(e.target.value)}
                      required={!selected}
                    />
                  </label>
                ) : (
                  <p className="muted">
                    Mount the provider key as {provider}-key in the gateway's
                    provider-secrets directory. The app and worker cannot read
                    this mount.
                  </p>
                )}
                <p className="muted">
                  The browser seals keys to the gateway. Stored keys are
                  write-only. Adapters have simulated verification; no live
                  compatibility claim for your model.
                </p>
              </>
            )}
            <label className="check-label">
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />
              Enable this connection
            </label>
            <fieldset>
              <legend>Allowed purposes</legend>
              {[
                "ask_interpretation",
                "ask_narration",
                "task_preparation",
                "task_narration",
                "clarification",
                "acquisition",
                "connection_test",
                "interpretation",
                "extraction",
                "repair",
              ].map((p) => (
                <label className="check-label" key={p}>
                  <input
                    type="checkbox"
                    checked={purposes.includes(p)}
                    onChange={(e) =>
                      setPurposes((v) =>
                        e.target.checked ? [...v, p] : v.filter((x) => x !== p),
                      )
                    }
                  />
                  {p.replaceAll("_", " ")}
                </label>
              ))}
            </fieldset>
            <button className="primary" disabled={busy}>
              Save connection
            </button>
          </form>
        </section>
      </div>
      {testConnection && (
        <section
          className="panel"
          ref={testPanel}
          tabIndex={-1}
          aria-label="Connection test"
        >
          <h2>Test {testConnection.name}</h2>
          <p>
            One call · {testConnection.provider} / {testConnection.model} ·
            version {testConnection.version}. Only a fixed connection-check
            prompt is sent.
          </p>
          <JsonEditor
            label="Connection-test limits"
            value={testCaps}
            onChange={setTestCaps}
            rows={6}
          />
          <div className="buttons">
            <button
              disabled={busy}
              className="primary"
              onClick={() =>
                void run(async () => {
                  const limits = parseJson(testCaps);
                  const meaning = JSON.stringify({
                    connection: testConnection.id,
                    version: testConnection.version,
                    limits,
                  });
                  if (testIntent.current?.meaning !== meaning)
                    testIntent.current = { meaning, key: crypto.randomUUID() };
                  const result = await api<Record<string, unknown>>(
                    `/connections/${testConnection.id}/test`,
                    {
                      method: "POST",
                      body: {
                        idempotency_key: testIntent.current.key,
                        expected_version: testConnection.version,
                        limits,
                      },
                    },
                  );
                  setTest(result);
                })
              }
            >
              Run one budgeted test
            </button>
            <button
              onClick={() => {
                setTestConnection(null);
                testIntent.current = null;
              }}
            >
              Close
            </button>
          </div>
          {test && (
            <>
              <p>
                Dispatch: <strong>{String(test.status)}</strong>
              </p>
              <JsonDetail
                label="Connection-test result and reservation"
                value={test}
              />
            </>
          )}
        </section>
      )}
      <Spending />
    </>
  );
}

export function Learning({
  adms,
  initialAdm = "",
  request = "",
  teachingDraft,
}: {
  adms: Adm[];
  initialAdm?: string;
  request?: string;
  teachingDraft?: { id: string; text: string; adm: string } | null;
}) {
  const [adm, setAdm] = useState(initialAdm),
    [connections, setConnections] = useState<Connection[]>([]),
    [settings, setSettings] = useState<Settings | null>(null),
    [connection, setConnection] = useState("");
  const [task, setTask] = useState(
      '{"description":"","acquisition_contract":{"profile":"adm-acquisition/1","required_symbols":[],"allowed_helpers":[],"allowed_retractions":[],"interfaces":{},"max_declarations":64,"max_bytes":131072}}',
    ),
    [limits, setLimits] = useState("{}"),
    [callLimits, setCallLimits] = useState("{}"),
    [publication, setPublication] = useState("review"),
    [construction, setConstruction] = useState(true),
    [disclose, setDisclose] = useState(false),
    [requestIds, setRequestIds] = useState(request);
  const [episodes, setEpisodes] = useState<Episode[]>([]),
    [selected, setSelected] = useState(""),
    [detail, setDetail] = useState<Episode | null>(null),
    [busy, setBusy] = useState(false),
    [error, setError] = useState(""),
    [readError, setReadError] = useState(""),
    [revision, setRevision] = useState("");
  const intent = useRef<{ meaning: string; key: string } | null>(null);
  useEffect(() => {
    if (teachingDraft) {
      setAdm(teachingDraft.adm);
      setTask(
        pretty({
          description: teachingDraft.text,
          acquisition_contract: {
            profile: "adm-acquisition/1",
            required_symbols: [],
            allowed_helpers: [],
            allowed_retractions: [],
            interfaces: {},
            max_declarations: 64,
            max_bytes: 131072,
          },
        }),
      );
      setDisclose(false);
    }
  }, [teachingDraft?.id]);
  useEffect(() => {
    let current = true;
    Promise.all([
      api<{ items: Connection[] }>("/connections"),
      api<Settings>("/learning"),
    ])
      .then(([c, s]) => {
        if (current) {
          setConnections(c.items);
          setSettings(s);
          setLimits(pretty(s.episode_caps));
          setCallLimits(pretty(s.call_caps));
        }
      })
      .catch((e) => setReadError(e.message));
    return () => {
      current = false;
    };
  }, []);
  useEffect(() => {
    if (!adm) return;
    let current = true;
    async function load() {
      try {
        const [page, info, ep] = await Promise.all([
          api<{ items: Episode[] }>(`/adms/${adm}/episodes`),
          api<Adm>(`/adms/${adm}`),
          selected
            ? api<Episode>(`/adms/${adm}/episodes/${selected}`)
            : Promise.resolve(null),
        ]);
        if (current) {
          setEpisodes(page.items);
          setRevision(info.revision_id!);
          setDetail(ep);
          setReadError("");
        }
      } catch (e) {
        if (current) setReadError((e as Error).message);
      }
    }
    void load();
    const timer = setInterval(() => void load(), 1000);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [adm, selected]);
  async function run(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const chosen = connections.find((c) => c.id === connection);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">BOUNDED KNOWLEDGE ACQUISITION</p>
          <h1>Learn, check, then publish.</h1>
          <p className="muted">
            Private drafts stay separate from accepted knowledge. Review and
            local checks control publication.
          </p>
        </div>
        <Badge>Explicit budgets</Badge>
      </div>
      {readError && (
        <Notice error>Could not refresh learning: {readError}</Notice>
      )}
      {error && <Notice error>{error}</Notice>}
      <section className="panel">
        <label>
          Target ADM
          <select
            value={adm}
            onChange={(e) => {
              setAdm(e.target.value);
              setSelected("");
              setDetail(null);
              setEpisodes([]);
              setRevision("");
              setRequestIds("");
            }}
          >
            <option value="">Choose a domain model</option>
            {adms
              .filter((a) => !a.archived && a.status === "ready")
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
        {adm && (
          <p className="muted">
            Current revision {short(revision)} · proposals and budget apply only
            to this ADM.
          </p>
        )}
      </section>
      {adm && (
        <div className="learning-grid">
          <section className="panel">
            <h2>Start an episode</h2>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                void run(async () => {
                  if (!chosen || !revision)
                    throw Error(
                      "Choose a ready connection and wait for the current revision.",
                    );
                  const body = {
                    expected_revision: revision,
                    connection_id: chosen.id,
                    connection_version: chosen.version,
                    task: parseJson(task),
                    construction,
                    publication,
                    disclose_model: disclose,
                    limits: parseJson(limits),
                    call_limits: parseJson(callLimits),
                    request_ids: requestIds.split(/[\s,]+/).filter(Boolean),
                  };
                  const meaning = JSON.stringify(body);
                  if (intent.current?.meaning !== meaning)
                    intent.current = { meaning, key: crypto.randomUUID() };
                  const result = await api<Episode>(`/adms/${adm}/episodes`, {
                    method: "POST",
                    body: { ...body, idempotency_key: intent.current.key },
                  });
                  setSelected(result.id);
                  intent.current = null;
                });
              }}
            >
              <label>
                Knowledge connection
                <select
                  required
                  value={connection}
                  onChange={(e) => setConnection(e.target.value)}
                >
                  <option value="">Choose a connection</option>
                  {connections
                    .filter((c) => c.purposes.includes("acquisition"))
                    .map((c) => (
                      <option
                        disabled={!c.enabled || c.status !== "ready"}
                        key={c.id}
                        value={c.id}
                      >
                        {c.name} · {c.model} · v{c.version}
                        {!c.enabled || c.status !== "ready"
                          ? " (unavailable)"
                          : ""}
                      </option>
                    ))}
                </select>
              </label>
              <JsonEditor
                label="Task and receiver-owned interfaces"
                value={task}
                onChange={setTask}
                rows={10}
              />
              <button
                type="button"
                onClick={() =>
                  void run(async () => {
                    const response = await fetch(
                      "/examples/learning-capacity.json",
                    );
                    if (!response.ok) throw Error("Example unavailable");
                    const value = parseJson(await response.text()) as {
                      task: unknown;
                    };
                    setTask(pretty(value.task));
                  })
                }
              >
                Load authored capacity task
              </button>
              <label>
                Publication
                <select
                  value={publication}
                  onChange={(e) => setPublication(e.target.value)}
                >
                  <option value="review">Review each complete candidate</option>
                  <option value="checked_auto">
                    Automatic after independent owner checks
                  </option>
                </select>
              </label>
              <p className="muted">
                Automatic publication requires installed owner requirements.
                Approval always preserves local admission checks.
              </p>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={construction}
                  onChange={(e) => setConstruction(e.target.checked)}
                />
                Construct private drafts across attempts
              </label>
              <label className="check-label">
                <input
                  type="checkbox"
                  checked={disclose}
                  onChange={(e) => setDisclose(e.target.checked)}
                />
                Include the accepted model in the provider context
              </label>
              <p className="muted">
                Every call includes the task, supplied interfaces, private draft
                and bounded diagnostic feedback. Choose disclosure
                intentionally.
              </p>
              <label>
                Pending request IDs (optional)
                <textarea
                  rows={2}
                  value={requestIds}
                  onChange={(e) => setRequestIds(e.target.value)}
                  placeholder="Comma or space separated"
                />
              </label>
              <p className="muted">
                Attached requests retry locally after publication. Cancelling
                all attached requests stops their episode. An episode with no
                attached requests is manual work.
              </p>
              <details>
                <summary>Episode and per-call budgets</summary>
                <JsonEditor
                  label="Episode limits"
                  value={limits}
                  onChange={setLimits}
                  rows={10}
                />
                <JsonEditor
                  label="Per-call limits"
                  value={callLimits}
                  onChange={setCallLimits}
                  rows={6}
                />
              </details>
              <button
                className="primary"
                disabled={
                  busy ||
                  !chosen ||
                  !settings ||
                  (chosen.provider !== "recorded" &&
                    !settings.remote_calls_enabled)
                }
              >
                Start bounded learning
              </button>
            </form>
          </section>
          <section className="panel">
            <h2>Episode history</h2>
            {!episodes.length && (
              <p className="muted">No learning episodes for this ADM.</p>
            )}
            <div className="operation-list">
              {episodes.map((ep) => (
                <button
                  className="episode-item"
                  aria-pressed={selected === ep.id}
                  key={ep.id}
                  onClick={() => setSelected(ep.id)}
                >
                  <span>
                    <code>{short(ep.id)}</code>
                    <small>{ep.reason || "Owner-authorized learning"}</small>
                  </span>
                  <Badge tone={ep.status === "accepted" ? "green" : "amber"}>
                    {ep.status.replaceAll("_", " ")}
                  </Badge>
                </button>
              ))}
            </div>
            {detail && (
              <div className="episode-detail">
                <h3>Episode {short(detail.id)}</h3>
                <p>
                  {detail.status === "acquiring"
                    ? "Call reserved; inspect dispatch status to distinguish queued from dispatched."
                    : `Status: ${detail.status.replaceAll("_", " ")}`}
                </p>
                <p>
                  {detail.usage?.calls || 0} calls charged or reserved ·{" "}
                  {detail.work.toLocaleString()} local work ·{" "}
                  {detail.usage?.unresolved || 0} unresolved reservations
                </p>
                <ProviderFailure failure={detail.provider_failure} />
                {detail.reason && !detail.provider_failure && (
                  <Notice>
                    {detail.reason.replaceAll("_", " ")}. Pending requests
                    remain available for further input.
                  </Notice>
                )}
                {!terminal(detail.status) && (
                  <button
                    disabled={busy}
                    onClick={() =>
                      void run(async () => {
                        setDetail(
                          await api<Episode>(
                            `/adms/${adm}/episodes/${detail.id}/cancel`,
                            { method: "POST" },
                          ),
                        );
                      })
                    }
                  >
                    Cancel episode
                  </button>
                )}
                {detail.grant_id && (
                  <button
                    className="text-button"
                    onClick={() =>
                      void run(async () => {
                        const data = await api<Record<string, unknown>>(
                          `/dispatches/${detail.grant_id}`,
                        );
                        setDetail({ ...detail, dispatch: data } as Episode);
                      })
                    }
                  >
                    Refresh dispatch details
                  </button>
                )}
                <JsonDetail
                  label="Usage, dispatch and immutable task"
                  value={detail}
                />
                <h3>Candidate timeline</h3>
                {detail.receipts?.map((r) => (
                  <article className="candidate-item" key={r.id}>
                    <div className="section-title">
                      <strong>Receipt {r.seq}</strong>
                      <Badge tone={r.status === "accepted" ? "green" : "amber"}>
                        {r.status.replaceAll("_", " ")}
                      </Badge>
                    </div>
                    {r.data.preview !== undefined && (
                      <JsonDetail
                        label="Proposed declarations"
                        value={r.data.preview}
                      />
                    )}
                    {r.status === "awaiting_review" && (
                      <>
                        <p>
                          Approval applies to revision {short(revision)}. A
                          changed revision requires review again.
                        </p>
                        <div className="buttons">
                          {[true, false].map((approve) => (
                            <button
                              key={String(approve)}
                              disabled={busy}
                              className={approve ? "primary" : "secondary"}
                              onClick={() =>
                                void run(async () => {
                                  setDetail(
                                    await api<Episode>(
                                      `/adms/${adm}/candidates/${r.id}/review`,
                                      {
                                        method: "POST",
                                        body: {
                                          expected_revision: revision,
                                          approve,
                                        },
                                      },
                                    ),
                                  );
                                })
                              }
                            >
                              {approve
                                ? "Approve for local checks"
                                : "Decline candidate"}
                            </button>
                          ))}
                        </div>
                      </>
                    )}
                    <JsonDetail
                      label="Candidate, diagnostics and decision"
                      value={r.data}
                    />
                  </article>
                ))}
              </div>
            )}
          </section>
        </div>
      )}
    </>
  );
}
