import { useCallback, useEffect, useRef, useState } from "react";
import { ApiError, api, authApi, download, saveSession, watch } from "./api.ts";
import { LoginSettings, Login } from "./Auth.tsx";
import type { Adm, Json, Limits, Model, Operation, System } from "./types.ts";
import { short } from "./types.ts";
import { Badge, CopyButton, Notice } from "./components.tsx";
import { Connections } from "./Connections.tsx";
import { Operations } from "./Operations.tsx";
import { Activity } from "./Activity.tsx";
import { Knowledge } from "./Knowledge.tsx";
import { DirectWorkspace } from "./DirectWorkspace.tsx";
import {
  PendingDeletions,
  OwnerLifecycle,
  forgetOutbox,
} from "./Lifecycle.tsx";
import { CreateModel, Settings } from "./Views.tsx";

const nav = [
  { id: "overview", label: "Overview", icon: "◫" },
  { id: "adms", label: "Domain models", icon: "◇" },
  { id: "connections", label: "Connections", icon: "⇄" },
  { id: "operations", label: "Operations", icon: "⚙" },
  { id: "login", label: "Login", icon: "○" },
];
type Route = {
  view: string;
  adm: string;
  tab: string;
  request: string;
  conversation: string;
};
function location(): Route {
  const p = new URLSearchParams(window.location.hash.slice(1));
  const oldView = p.get("view") || "adms";
  const view =
    oldView === "account"
      ? "login"
      : ["sources", "learning"].includes(oldView)
        ? "adms"
        : oldView;
  const oldTab = ["sources", "learning"].includes(oldView)
    ? "teach"
    : p.get("tab") || "ask";
  return {
    view: nav.some((n) => n.id === view) ? view : "adms",
    adm: p.get("adm") || "",
    tab: ["ask", "teach", "model", "history", "settings"].includes(oldTab)
      ? oldTab
      : "ask",
    request: p.get("request") || "",
    conversation: p.get("conversation") || "",
  };
}
function go(part: Partial<Route>) {
  window.location.hash = new URLSearchParams({
    ...location(),
    ...part,
  }).toString();
}
const pause = (ms: number) => new Promise((resolve) => setTimeout(resolve, ms));

function ModelList({ adms }: { adms: Adm[] }) {
  const [filter, setFilter] = useState("active");
  const visible = adms.filter(
    (a) =>
      filter === "all" || (filter === "archived" ? a.archived : !a.archived),
  );
  return adms.length ? (
    <>
      <label className="field">
        Show models
        <select
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
        >
          <option value="active">
            Active ({adms.filter((a) => !a.archived).length})
          </option>
          <option value="archived">
            Archived ({adms.filter((a) => a.archived).length})
          </option>
          <option value="all">All ({adms.length})</option>
        </select>
      </label>
      {!visible.length && (
        <p>
          No models in this view. Archived models retain their knowledge and
          history.
        </p>
      )}

      <section className="model-list" aria-label="Domain models">
        {visible.map((a) => (
          <button
            key={a.id}
            className="model-row"
            aria-label={`${a.name}, ${a.archived ? "archived" : a.status}, ${a.mode} mode`}
            disabled={!["ready", "failed"].includes(a.status)}
            onClick={() =>
              go({
                view: "adms",
                adm: a.id,
                tab: "ask",
                request: "",
                conversation: "",
              })
            }
          >
            <span className="model-icon" aria-hidden="true">
              ◇
            </span>
            <span className="model-name">
              <strong>{a.name}</strong>
              <small>Independent model · Ask and Teach</small>
            </span>
            <Badge>{a.mode}</Badge>
            <Badge tone={a.archived ? "amber" : "green"}>
              {a.archived ? "Archived" : a.status}
            </Badge>
            <span aria-hidden="true">↗</span>
          </button>
        ))}
      </section>
    </>
  ) : (
    <section className="panel empty">
      <span className="result-mark" aria-hidden="true">
        ◇
      </span>
      <h2>Your first model starts here.</h2>
      <p>
        Create an empty ADM, import a snapshot, or try an example sandbox from
        Overview.
      </p>
    </section>
  );
}

function Instance({
  adm,
  route,
  onChanged,
  busy,
  run,
  exportSnapshot,
  clone,
}: {
  adm: Adm;
  route: Route;
  onChanged: () => void;
  busy: boolean;
  run: (f: () => Promise<void>) => void;
  exportSnapshot: () => void;
  clone: () => void;
}) {
  const [model, setModel] = useState<Model | null>(null),
    [error, setError] = useState(""),
    [stream, setStream] = useState("Connecting to updates");
  useEffect(() => {
    const c = new AbortController();
    setModel(null);
    setError("");
    api<Model>(`/adms/${adm.id}/model`, { signal: c.signal })
      .then(setModel)
      .catch((e) => {
        if (!c.signal.aborted) setError(e.message);
      });
    return () => c.abort();
  }, [adm.id, adm.revision_id]);
  useEffect(() => {
    const c = new AbortController();
    let timer: ReturnType<typeof setTimeout> | undefined;
    void watch(
      adm.id,
      c.signal,
      () => {
        clearTimeout(timer);
        timer = setTimeout(onChanged, 150);
      },
      setStream,
    );
    return () => {
      c.abort();
      clearTimeout(timer);
    };
  }, [adm.id, onChanged]);
  return (
    <>
      <div className="model-heading">
        <div>
          <button
            className="text-button"
            onClick={() => go({ adm: "", request: "" })}
          >
            ← All domain models
          </button>
          <h1>{adm.name}</h1>
          <p className="muted">
            <code>{short(adm.id)}</code> <CopyButton value={adm.id} /> ·{" "}
            {stream}
          </p>
        </div>
        <div className="chips">
          {adm.name.startsWith("[Sandbox]") && (
            <Badge tone="blue">Sandbox · independent instance</Badge>
          )}
          <Badge tone={adm.archived ? "amber" : "green"}>
            {adm.archived
              ? "Archived"
              : adm.status === "ready"
                ? "Accepted model"
                : adm.status}
          </Badge>
          <Badge>{adm.mode} mode</Badge>
        </div>
      </div>
      <nav className="tabs" aria-label="Model views">
        {["ask", "teach", "model", "history", "settings"].map((tab) => (
          <button
            key={tab}
            aria-current={route.tab === tab ? "page" : undefined}
            onClick={() => go({ tab, conversation: "" })}
          >
            {tab === "model"
              ? "Model & evidence"
              : tab[0].toUpperCase() + tab.slice(1)}
          </button>
        ))}
      </nav>
      {error && <Notice error>{error}</Notice>}
      {adm.archived && (
        <Notice>
          This ADM is archived. Historical results, accepted knowledge and
          snapshot exports remain available.
        </Notice>
      )}
      {["ask", "teach"].includes(route.tab) ? (
        <DirectWorkspace
          key={`${adm.id}:${route.tab}`}
          adm={adm}
          channel={route.tab as "ask" | "teach"}
        />
      ) : !model ? (
        <Notice>Loading accepted model…</Notice>
      ) : route.tab === "model" ? (
        <Knowledge adm={adm} model={model} />
      ) : route.tab === "settings" ? (
        <Settings {...{ adm, onChanged, busy, run, exportSnapshot, clone }} />
      ) : route.tab === "history" ? (
        <Activity adm={adm.id} />
      ) : null}
    </>
  );
}

export default function App() {
  const [route, setRoute] = useState(location),
    [system, setSystem] = useState<System | null>(null),
    [authed, setAuthed] = useState(false),
    [checking, setChecking] = useState(true),
    [adms, setAdms] = useState<Adm[]>([]),
    [operations, setOperations] = useState<Operation[]>([]),
    [limits, setLimits] = useState<Limits | null>(null),
    [tick, setTick] = useState(0),
    [error, setError] = useState(""),
    [readError, setReadError] = useState(""),
    [sessionReadError, setSessionReadError] = useState(false),
    [busy, setBusy] = useState(false),
    [creating, setCreating] = useState(false),
    [message, setMessage] = useState("");
  const intent = useRef<{ meaning: string; key: string } | null>(null);
  const refresh = useCallback(() => setTick((t) => t + 1), []);
  useEffect(() => {
    const changed = () => setRoute(location());
    window.addEventListener("hashchange", changed);
    return () => window.removeEventListener("hashchange", changed);
  }, []);
  useEffect(() => {
    const expired = () => {
      setAuthed(false);
      setChecking(false);
    };
    window.addEventListener("adm-session-expired", expired);
    return () => window.removeEventListener("adm-session-expired", expired);
  }, []);
  const authenticate = useCallback(async (background = false) => {
    // Returning from another window or a file chooser must not unmount forms.
    // Only initial entry and explicit sign-in replace the workspace while checking.
    if (!background) setChecking(true);
    try {
      const current = await authApi<{
        id: string;
        csrf: string;
        request_limits: Limits;
      }>("/me");
      saveSession({ id: current.id, csrf: current.csrf });
      setLimits(current.request_limits);
      setAuthed(true);
      setSessionReadError(false);
    } catch (e) {
      if (!background || (e instanceof ApiError && e.status === 401))
        setAuthed(false);
      else setSessionReadError(true);
    } finally {
      if (!background) setChecking(false);
    }
  }, []);
  useEffect(() => {
    void authenticate();
    const listener = () => void authenticate(true);
    window.addEventListener("focus", listener);
    return () => window.removeEventListener("focus", listener);
  }, [authenticate]);
  useEffect(() => {
    let current = true;
    const load = () =>
      api<System>("/system")
        .then((v) => {
          if (current) setSystem(v);
        })
        .catch(() => {
          if (current) setSystem(null);
        });
    void load();
    const timer = setInterval(load, 10_000);
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!authed) return;
    const c = new AbortController();
    Promise.all([
      api<{ items: Adm[] }>("/adms", { signal: c.signal }),
      api<{ items: Operation[] }>(
        `/operations?since_ms=${Date.now() - 7 * 24 * 60 * 60 * 1000}&include_deletions=true`,
        { signal: c.signal },
      ),
    ])
      .then(([a, o]) => {
        setAdms((previous) => {
          for (const old of previous)
            if (!a.items.some((x) => x.id === old.id)) forgetOutbox(old.id);
          return a.items;
        });
        setOperations(o.items);
        setReadError("");
      })
      .catch((e) => {
        if (!c.signal.aborted) setReadError(e.message);
      });
    return () => c.abort();
  }, [authed, tick]);
  useEffect(() => {
    if (!authed) return;
    const timer = setInterval(refresh, 10_000);
    return () => clearInterval(timer);
  }, [authed, refresh]);
  async function run(f: () => Promise<void>) {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      await f();
      refresh();
    } catch (e) {
      setMessage("");
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function operation(
    path: string,
    body: Record<string, unknown>,
  ): Promise<Operation> {
    const meaning = JSON.stringify({ path, body });
    if (intent.current?.meaning !== meaning)
      intent.current = { meaning, key: crypto.randomUUID() };
    let value = await api<Operation>(path, {
      method: "POST",
      body: { ...body, idempotency_key: intent.current.key },
    });
    const end = Date.now() + 60_000;
    while (
      ["queued", "running", "received", "validating"].includes(value.status) &&
      Date.now() < end
    ) {
      setMessage(
        `${value.status === "received" ? "Queued for local validation" : "Checking locally"} · operation ${short(value.operation_id)}`,
      );
      await pause(400);
      value = await api<Operation>(`/operations/${value.operation_id}`);
    }
    if (value.status !== "succeeded") {
      if (value.status === "failed") intent.current = null;
      throw Error(
        value.error?.message ||
          "The operation is pending. Inspect recent operations before starting another one.",
      );
    }
    intent.current = null;
    setMessage("");
    return value;
  }
  async function create(name: string, mode: string, snapshot?: Json) {
    setBusy(true);
    setError("");
    try {
      const result = await operation("/adms", {
        name,
        mode,
        ...(snapshot ? { snapshot } : {}),
      });
      setCreating(false);
      go({
        view: "adms",
        adm: result.result!.adm_id!,
        tab: "ask",
        request: "",
        conversation: "",
      });
      refresh();
    } catch (error) {
      setMessage("");
      throw error;
    } finally {
      setBusy(false);
    }
  }
  async function exportOf(adm: Adm) {
    const result = await operation(`/adms/${adm.id}/snapshot-exports`, {});
    return result.result!.snapshot!;
  }
  const chosen = adms.find((a) => a.id === route.adm);
  if (checking)
    return (
      <div className="loading-screen" role="status">
        Opening workspace…
      </div>
    );
  if (!authed)
    return (
      <Login
        ready={!!system?.operational}
        onLogin={() => void authenticate()}
      />
    );
  return (
    <div className="shell">
      <a
        className="skip-link"
        href="#main"
        onClick={(e) => {
          e.preventDefault();
          document.getElementById("main")?.focus();
        }}
      >
        Skip to content
      </a>
      <aside className="sidebar">
        <a href="#view=overview" className="brand">
          AWM<span> / </span>ADM
        </a>
        <div className="workspace-label">
          <span className="dot" /> WORKSPACE
        </div>
        <nav aria-label="Main navigation">
          {nav.map((n) => (
            <button
              key={n.id}
              aria-current={route.view === n.id ? "page" : undefined}
              onClick={() => {
                setCreating(false);
                go({ view: n.id, adm: "", request: "" });
              }}
            >
              <span aria-hidden="true">{n.icon}</span>
              {n.label}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <span
            className={`dot ${system?.available.local_serving ? "" : "offline"}`}
          />
          {system?.available.local_serving
            ? "Local serving ready"
            : "Service unavailable"}
          <small>Finite models · explicit boundaries</small>
          <button
            className="text-button"
            onClick={() =>
              void run(async () => {
                await authApi("/logout", {});
                saveSession(null);
                setAuthed(false);
              })
            }
          >
            Sign out
          </button>
        </div>
      </aside>
      <div className="main-shell">
        <header className="topbar">
          <span>
            Workspace <span className="slash">/</span>{" "}
            {nav.find((n) => n.id === route.view)?.label || "Overview"}
          </span>
          <Badge tone={system?.available.local_serving ? "green" : "amber"}>
            {system?.available.local_serving
              ? "Local execution"
              : "Service unavailable"}
          </Badge>
        </header>
        <main id="main" tabIndex={-1}>
          {sessionReadError && (
            <Notice error>
              Session check could not reach the service. Your draft is
              preserved; requests still require a valid session.
              <button
                className="text-button"
                onClick={() => void authenticate(true)}
              >
                Check session again
              </button>
            </Notice>
          )}
          {readError && (
            <Notice error>
              Connection interrupted. Showing last-known state; retrying
              automatically.
            </Notice>
          )}
          {error && (
            <Notice error>
              {error}{" "}
              <button
                className="text-button"
                onClick={() => {
                  setError("");
                  refresh();
                }}
              >
                Refresh state
              </button>
            </Notice>
          )}
          {message && <Notice>{message}</Notice>}
          {route.view === "overview" ? (
            <>
              <div className="page-heading">
                <div>
                  <p className="eyebrow">YOUR KNOWLEDGE, UNDER YOUR CONTROL</p>
                  <h1>
                    Local intelligence.
                    <br />A clear view of every model.
                  </h1>
                  <p className="muted">
                    Work with accepted knowledge. Inspect the reasoning. Keep
                    ownership local.
                  </p>
                </div>
                <button
                  className="primary"
                  onClick={() => {
                    go({ view: "adms", adm: "" });
                    setCreating(true);
                  }}
                >
                  + Create model
                </button>
              </div>
              <section className="metrics" aria-label="Runtime readiness">
                {[
                  [
                    "Domain models",
                    String(adms.length),
                    "Independent instances",
                  ],
                  [
                    "Local serving",
                    system?.available.local_serving ? "Ready" : "Unavailable",
                    "Runs without a provider",
                  ],
                  [
                    "Lean checker",
                    system?.available.lean ? "Available" : "Unavailable",
                    "Kernel proof checks",
                  ],
                  [
                    "Learning",
                    system?.available.learning ? "Available" : "Unavailable",
                    "Learn through Teach",
                  ],
                ].map(([label, value, note]) => (
                  <article className="panel" key={label}>
                    <p>{label}</p>
                    <strong>{value}</strong>
                    <small>{note}</small>
                  </article>
                ))}
              </section>
              <div className="section-title">
                <div>
                  <h2>Your domain models</h2>
                  <p className="muted">
                    Each ADM owns its knowledge, requirements and history.
                  </p>
                </div>
                <button
                  className="text-button"
                  onClick={() => go({ view: "adms" })}
                >
                  View all →
                </button>
              </div>
              <ModelList adms={adms.filter((a) => !a.archived).slice(0, 4)} />
              <section className="panel examples">
                <div>
                  <p className="eyebrow">EXPLORE IN A SANDBOX</p>
                  <h2>Start with a small, inspectable model.</h2>
                  <p className="muted">
                    Each example creates a new independent sandbox ADM. Archive
                    it in its Settings to hide it from the active model list;
                    its knowledge and history remain available. Their domain
                    rules are data, not built into the engine.
                  </p>
                </div>
                <div className="buttons">
                  {[
                    ["tanks", "Water tanks"],
                    ["access", "Access permissions"],
                  ].map(([id, name]) => (
                    <button
                      key={id}
                      className="secondary"
                      disabled={busy}
                      onClick={() =>
                        void run(async () => {
                          const response = await fetch(
                            `/examples/${id}.snapshot.json`,
                          );
                          if (!response.ok)
                            throw Error("Example snapshot unavailable");
                          await create(
                            `[Sandbox] ${name}`,
                            "backward",
                            await response.json(),
                          );
                        })
                      }
                    >
                      {name} ↗
                    </button>
                  ))}
                </div>
              </section>
              <section className="panel">
                <h2>Recent model operations</h2>
                <p className="muted">
                  Past 7 days · up to 50 latest create, import, export and
                  delete operations.
                </p>
                {!operations.length ? (
                  <p>No model operations in the past 7 days.</p>
                ) : (
                  <div className="operation-list">
                    {operations.map((o) => (
                      <div key={o.operation_id}>
                        <span>
                          <code>{short(o.operation_id)}</code> · {o.kind}
                          {o.created_at_ms !== undefined && (
                            <small>
                              <time
                                dateTime={new Date(
                                  o.created_at_ms,
                                ).toISOString()}
                              >
                                {new Date(o.created_at_ms).toLocaleString()}
                              </time>
                            </small>
                          )}
                        </span>
                        <Badge
                          tone={
                            ["succeeded", "deleted"].includes(o.status)
                              ? "green"
                              : "amber"
                          }
                        >
                          {o.status}
                        </Badge>
                        {o.kind !== "delete" && (
                          <button
                            className="text-button"
                            disabled={busy}
                            onClick={() =>
                              void run(async () => {
                                const full = await api<Operation>(
                                  `/operations/${o.operation_id}`,
                                );
                                if (
                                  full.status === "succeeded" &&
                                  full.result?.snapshot
                                )
                                  download(
                                    `adm-${short(full.adm_id)}.snapshot.json`,
                                    full.result.snapshot,
                                  );
                                else if (
                                  full.status === "succeeded" &&
                                  full.result?.adm_id
                                )
                                  go({
                                    view: "adms",
                                    adm: full.result.adm_id,
                                    tab: "ask",
                                    request: "",
                                  });
                                else
                                  setMessage(
                                    full.error?.message ||
                                      `Operation ${full.status}`,
                                  );
                              })
                            }
                          >
                            {o.kind === "export" ? "Download" : "Inspect"}
                          </button>
                        )}
                      </div>
                    ))}
                  </div>
                )}
              </section>
              <PendingDeletions onChanged={refresh} />
            </>
          ) : route.view === "adms" ? (
            <>
              {creating && (
                <CreateModel
                  onClose={() => setCreating(false)}
                  onCreate={create}
                  busy={busy}
                />
              )}{" "}
              {chosen?.status === "failed" ? (
                <OwnerLifecycle adm={chosen} onChanged={refresh} />
              ) : chosen && limits ? (
                <Instance
                  key={chosen.id}
                  adm={chosen}
                  route={route}
                  onChanged={refresh}
                  busy={busy}
                  run={(f) => void run(f)}
                  exportSnapshot={() =>
                    void run(async () =>
                      download(
                        `adm-${short(chosen.id)}.snapshot.json`,
                        await exportOf(chosen),
                      ),
                    )
                  }
                  clone={() =>
                    void run(async () => {
                      const snapshot = await exportOf(chosen);
                      await create(
                        `[Sandbox] ${chosen.name.replace(/^\[Sandbox\] /, "").slice(0, 100)}`,
                        chosen.mode,
                        snapshot,
                      );
                    })
                  }
                />
              ) : (
                <>
                  <div className="page-heading">
                    <div>
                      <p className="eyebrow">INDEPENDENT BY DESIGN</p>
                      <h1>Domain models</h1>
                      <p className="muted">
                        Start empty or import accepted knowledge. No domain is
                        fixed by the engine.
                      </p>
                    </div>
                    <button
                      className="primary"
                      onClick={() => setCreating(true)}
                    >
                      + Create model
                    </button>
                  </div>
                  {route.adm && !chosen && (
                    <Notice>
                      The requested model is not available. Select a model below
                      or refresh.
                    </Notice>
                  )}
                  <ModelList adms={adms} />
                </>
              )}
            </>
          ) : route.view === "login" ? (
            <LoginSettings
              onSignedOut={() => {
                saveSession(null);
                setAuthed(false);
              }}
            />
          ) : route.view === "operations" ? (
            <Operations />
          ) : route.view === "connections" ? (
            <Connections />
          ) : (
            <section className="panel future">
              <Badge tone="amber">Not available yet</Badge>
              <h1>
                {nav.find((n) => n.id === route.view)?.label || "Not found"}
              </h1>
              <p>
                {route.view === "connections"
                  ? "Provider management is unavailable in this server mode. Use the full Docker runtime for connections."
                  : route.view === "sources"
                    ? "Source intake is unavailable in this server mode. Use the full Docker runtime for supplied material."
                    : "Background learning is unavailable in this server mode. No provider work is started by this view."}
              </p>
              <button
                className="secondary"
                onClick={() => go({ view: "adms" })}
              >
                Work with a local model →
              </button>
            </section>
          )}
        </main>
        <footer>
          AWM-ADM <span>{system?.version} · Workspace</span>
        </footer>
      </div>
    </div>
  );
}
