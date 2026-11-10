import { useEffect, useRef, useState } from "react";
import { api, readJsonFile } from "./api.ts";
import type {
  Adm,
  Json,
  Model,
  Page,
  RequestItem,
  RequestView,
} from "./types.ts";
import { pretty, short } from "./types.ts";
import { parseJson } from "./query.ts";
import { OwnerLifecycle } from "./Lifecycle.tsx";
import {
  Badge,
  JsonDetail,
  JsonEditor,
  Notice,
  ResultPanel,
  Status,
} from "./components.tsx";

export function CreateModel({
  onClose,
  onCreate,
  busy,
}: {
  onClose: () => void;
  onCreate: (name: string, mode: string, snapshot?: Json) => Promise<void>;
  busy: boolean;
}) {
  const [name, setName] = useState(""),
    [mode, setMode] = useState("backward"),
    [kind, setKind] = useState("empty"),
    [snapshot, setSnapshot] = useState<Json | undefined>(),
    [raw, setRaw] = useState(""),
    [error, setError] = useState("");
  return (
    <section className="panel create-panel" aria-label="Create a domain model">
      <div className="section-title">
        <div>
          <p className="eyebrow">AN INDEPENDENT INSTANCE</p>
          <h2>Create a domain model</h2>
        </div>
        <button className="text-button" disabled={busy} onClick={onClose}>
          Close
        </button>
      </div>
      <form
        onSubmit={async (e) => {
          e.preventDefault();
          setError("");
          try {
            const value =
              kind === "import" ? (raw ? parseJson(raw) : snapshot) : undefined;
            if (kind === "import" && !value)
              throw Error("Choose or paste a snapshot.");
            await onCreate(name, mode, value);
          } catch (err) {
            setError((err as Error).message);
          }
        }}
      >
        <div className="two-columns">
          <div>
            <label htmlFor="model-name">Model name</label>
            <input
              id="model-name"
              required
              maxLength={128}
              value={name}
              onChange={(e) => setName(e.target.value)}
              placeholder="A name for your ADM"
            />
          </div>
          <div>
            <label htmlFor="initial-mode">Conflict mode</label>
            <select
              id="initial-mode"
              value={mode}
              onChange={(e) => setMode(e.target.value)}
            >
              <option value="backward">
                Backward · preserve earlier knowledge
              </option>
              <option value="forward">Forward · prefer later knowledge</option>
            </select>
          </div>
        </div>
        <label htmlFor="start-from">Start from</label>
        <select
          id="start-from"
          value={kind}
          onChange={(e) => setKind(e.target.value)}
        >
          <option value="empty">An empty domain theory</option>
          <option value="import">A checked snapshot</option>
        </select>
        {kind === "empty" ? (
          <p className="muted">
            No domain is required. An empty ADM reports its capabilities; domain
            operations become available when a model is loaded.
          </p>
        ) : (
          <>
            <label htmlFor="snapshot-file">Snapshot JSON file</label>
            <input
              id="snapshot-file"
              type="file"
              accept="application/json,.json"
              onChange={async (e) => {
                const file = e.target.files?.[0];
                e.target.value = "";
                if (file)
                  try {
                    setSnapshot(await readJsonFile(file));
                    setRaw("");
                    setError("");
                  } catch (err) {
                    setError((err as Error).message);
                  }
              }}
            />
            {snapshot && (
              <small>
                Snapshot selected. The service will validate it before creating
                an instance.
              </small>
            )}
            <details>
              <summary>Advanced: paste a snapshot</summary>
              <JsonEditor
                label="Or paste snapshot JSON"
                value={raw}
                onChange={setRaw}
                rows={5}
              />
            </details>
            <p className="muted">
              Creates a new independent ADM. Proof status, requests and
              credentials are not imported.
            </p>
          </>
        )}
        {error && <Notice error>{error}</Notice>}
        <button className="primary" disabled={busy}>
          {busy ? "Checking and creating…" : "Create model"}
        </button>
      </form>
    </section>
  );
}

export function ModelBrowser({ adm, model }: { adm: Adm; model: Model }) {
  const selection = useRef(0);
  const [search, setSearch] = useState(""),
    [revision, setRevision] = useState(model.revision_id),
    [view, setView] = useState(model),
    [versions, setVersions] = useState<
      Page<{ revision_id: string; context: Model["context"] }>
    >({ items: [], next_cursor: null }),
    [error, setError] = useState("");
  useEffect(() => {
    let current = true;
    setRevision(model.revision_id);
    setView(model);
    api<typeof versions>(`/adms/${adm.id}/versions?limit=100&order=desc`)
      .then((v) => {
        if (current) setVersions(v);
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [adm.id, model]);
  async function choose(id: string) {
    const turn = ++selection.current;
    setRevision(id);
    try {
      const result = await api<Model>(`/adms/${adm.id}/model?revision=${id}`);
      if (selection.current === turn) {
        setView(result);
        setError("");
      }
    } catch (e) {
      if (selection.current === turn) setError((e as Error).message);
    }
  }
  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <p className="eyebrow">ACCEPTED KNOWLEDGE</p>
          <h2>Model & evidence</h2>
        </div>
        <Badge>{Object.keys(view.declarations).length} declarations</Badge>
      </div>
      <div className="two-columns">
        <div>
          <label htmlFor="model-search">Find a declaration</label>
          <input
            id="model-search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Filter by name or kind"
          />
        </div>
        <div>
          <label htmlFor="revision">Version / owner epoch</label>
          <select
            id="revision"
            value={revision}
            onChange={(e) => void choose(e.target.value)}
          >
            {versions.items.map((v) => (
              <option key={v.revision_id} value={v.revision_id}>
                {short(v.context.theory_version)} · epoch{" "}
                {v.context.policy_epoch}
                {v.revision_id === model.revision_id ? " · current" : ""}
              </option>
            ))}
          </select>
          {versions.next_cursor !== null && (
            <button
              className="text-button"
              onClick={async () => {
                try {
                  const page = await api<typeof versions>(
                    `/adms/${adm.id}/versions?limit=100&order=desc&after=${versions.next_cursor}`,
                  );
                  setVersions({
                    items: [...versions.items, ...page.items],
                    next_cursor: page.next_cursor,
                  });
                } catch (e) {
                  setError((e as Error).message);
                }
              }}
            >
              Load older versions
            </button>
          )}
        </div>
      </div>
      {error && <Notice error>{error}</Notice>}
      {view.revision_id !== model.revision_id && (
        <Notice>
          Viewing a historical revision. Playground requests use the current
          accepted model.
        </Notice>
      )}
      <div className="declarations">
        {Object.entries(view.declarations)
          .filter(([s, d]) =>
            (s + " " + d.kind).toLowerCase().includes(search.toLowerCase()),
          )
          .map(([s, d]) => (
            <details key={s}>
              <summary>
                <span>{s}</span>
                <Badge>{d.kind}</Badge>
              </summary>
              <pre>{pretty(d)}</pre>
            </details>
          ))}
      </div>
      {Object.keys(view.declarations).length === 0 && (
        <div className="empty">
          <h3>No domain knowledge yet</h3>
          <p>
            This is a valid empty ADM. Import a snapshot into a new instance to
            explore an existing model.
          </p>
        </div>
      )}
      <JsonDetail label="Exact revision context" value={view.context} />
      <JsonDetail
        label="Evidence, declaration origins and admission records"
        value={view.artifacts.filter((a) =>
          ["evidence", "provenance", "admission"].includes(a.role),
        )}
      />
      <p className="footnote">
        Recorded evidence and admission are provenance. They do not establish
        that a source is externally true.
      </p>
    </section>
  );
}

export function History({
  adm,
  refresh,
  requestId,
  onRequest,
}: {
  adm: string;
  refresh: number;
  requestId: string;
  onRequest: (id: string) => void;
}) {
  const [page, setPage] = useState<Page<RequestItem>>({
      items: [],
      next_cursor: null,
    }),
    [record, setRecord] = useState<RequestView | null>(null),
    [error, setError] = useState(""),
    [listError, setListError] = useState(""),
    [detailError, setDetailError] = useState(""),
    [busy, setBusy] = useState(false);
  useEffect(() => {
    let current = true;
    api<Page<RequestItem>>(`/adms/${adm}/requests?limit=50&order=desc`)
      .then((p) => {
        if (current) {
          setPage(p);
          setListError("");
        }
      })
      .catch((e) => {
        if (current) setListError(e.message);
      });
    return () => {
      current = false;
    };
  }, [adm, refresh]);
  useEffect(() => {
    let current = true;
    if (requestId)
      api<RequestView>(`/adms/${adm}/requests/${requestId}`)
        .then((r) => {
          if (current) {
            setRecord(r);
            setDetailError("");
          }
        })
        .catch((e) => {
          if (current) setDetailError(e.message);
        });
    else setRecord(null);
    return () => {
      current = false;
    };
  }, [adm, requestId, refresh]);
  async function action(a: string) {
    setBusy(true);
    try {
      setRecord(
        await api<RequestView>(`/adms/${adm}/requests/${requestId}/${a}`, {
          method: "POST",
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="history-grid">
      <section className="panel">
        <p className="eyebrow">PERSISTED REQUESTS</p>
        <h2>Request history</h2>
        {(listError || detailError) && (
          <Notice>
            Could not refresh history: {listError || detailError}. Any history
            shown is the last retrieved state.
          </Notice>
        )}
        {error && <Notice error>{error}</Notice>}
        {!page.items.length && (
          <div className="empty">Your local requests will appear here.</div>
        )}
        <div className="request-list">
          {page.items.map((r) => (
            <button
              key={r.request_id}
              className={r.request_id === requestId ? "selected" : ""}
              onClick={() => onRequest(r.request_id)}
            >
              <span>
                <code>{short(r.request_id)}</code>
                <small>
                  Epoch {r.pinned_context.policy_epoch} ·{" "}
                  {short(r.pinned_context.theory_root)}
                </small>
              </span>
              <Status status={r.status} />
            </button>
          ))}
        </div>
        {page.next_cursor !== null && (
          <button
            className="secondary"
            onClick={async () => {
              try {
                const next = await api<Page<RequestItem>>(
                  `/adms/${adm}/requests?order=desc&limit=50&after=${page.next_cursor}`,
                );
                setPage({
                  items: [...page.items, ...next.items],
                  next_cursor: next.next_cursor,
                });
              } catch (e) {
                setError((e as Error).message);
              }
            }}
          >
            Load older requests
          </button>
        )}
      </section>
      {record ? (
        <ResultPanel
          request={record}
          busy={busy}
          onCancel={() => void action("cancel")}
          onRetry={() => void action("retry")}
        />
      ) : (
        <section className="panel empty">
          Select a request to inspect its result and exact context.
        </section>
      )}
    </div>
  );
}

export function Settings({
  adm,
  onChanged,
  busy,
  run,
  exportSnapshot,
  clone,
}: {
  adm: Adm;
  onChanged: () => void;
  busy: boolean;
  run: (f: () => Promise<void>) => void;
  exportSnapshot: () => void;
  clone: () => void;
}) {
  const [policy, setPolicy] = useState(""),
    [epoch, setEpoch] = useState(adm.policy_epoch),
    [mode, setMode] = useState(adm.mode),
    [error, setError] = useState(""),
    [archive, setArchive] = useState(false);
  useEffect(() => {
    let current = true;
    setMode(adm.mode);
    api<{ policy: Json; policy_epoch: number }>(`/adms/${adm.id}/requirements`)
      .then((v) => {
        if (current) {
          setPolicy(pretty(v.policy));
          setEpoch(v.policy_epoch);
        }
      })
      .catch((e) => {
        if (current) setError(e.message);
      });
    return () => {
      current = false;
    };
  }, [adm.id, adm.policy_epoch]);
  return (
    <div className="settings-grid">
      <OwnerLifecycle adm={adm} onChanged={onChanged} />
      <section className="panel">
        <p className="eyebrow">OWNER CONTROLS</p>
        <h2>Learning precedence</h2>
        <p className="muted">
          Both modes enforce the same admission requirements. Switching affects
          future conflict decisions only. Both modes can learn nonconflicting
          knowledge. Existing task decisions may need to be renewed after a
          switch.
        </p>
        <label htmlFor="conflict-mode">Conflict mode</label>
        <select
          id="conflict-mode"
          value={mode}
          onChange={(e) => setMode(e.target.value as Adm["mode"])}
        >
          <option value="backward">Backward · retain earlier knowledge</option>
          <option value="forward">Forward · prefer later knowledge</option>
        </select>
        <p className="muted">
          “Earlier” and “later” refer to learning-result arrival at this ADM.
          Mode switches apply to future conflict decisions.
        </p>
        <button
          className="primary"
          disabled={busy || adm.archived || mode === adm.mode}
          onClick={() =>
            run(async () => {
              await api(`/adms/${adm.id}/settings`, {
                method: "PATCH",
                body: { expected_epoch: adm.policy_epoch, mode },
              });
              onChanged();
            })
          }
        >
          Save mode
        </button>
        <hr />
        <h3>Independent snapshots</h3>
        <p className="muted">
          Export a portable model or clone it into a separate sandbox for
          experiments. A model snapshot contains accepted knowledge and
          evidence; a whole-service backup also contains accounts, conversations
          and operational state.
        </p>
        <div className="buttons">
          <button
            className="secondary"
            disabled={busy}
            onClick={exportSnapshot}
          >
            Export snapshot
          </button>
          <button className="secondary" disabled={busy} onClick={clone}>
            Clone sandbox
          </button>
        </div>
        <hr />
        <details>
          <summary>Advanced: archive this model</summary>
          <h3>Archive this model</h3>
          <p className="muted">
            Stops new work and fences active requests. Retains the model and
            history. Unarchiving is not implemented.
          </p>
          <label className="check">
            <input
              type="checkbox"
              checked={archive}
              onChange={(e) => setArchive(e.target.checked)}
            />
            I intend to archive {adm.name}
          </label>
          <button
            className="danger"
            disabled={busy || adm.archived || !archive}
            onClick={() =>
              run(async () => {
                await api(`/adms/${adm.id}/archive`, {
                  method: "POST",
                  body: { expected_epoch: adm.policy_epoch },
                });
                onChanged();
              })
            }
          >
            Archive model
          </button>
        </details>
      </section>
      <section className="panel">
        <p className="eyebrow">INDEPENDENT OF PROVIDERS</p>
        <h2>Owner requirements</h2>
        <p className="muted">
          The complete policy is checked locally before installation. Saving it
          changes the owner epoch and fences outstanding requests.
        </p>
        {error && <Notice error>{error}</Notice>}
        <JsonEditor
          label="Conformance policy JSON"
          value={policy}
          onChange={setPolicy}
          rows={18}
        />
        <button
          className="primary"
          disabled={busy || adm.archived}
          onClick={() =>
            run(async () => {
              await api(`/adms/${adm.id}/requirements`, {
                method: "PUT",
                body: { expected_epoch: epoch, policy: parseJson(policy) },
              });
              onChanged();
            })
          }
        >
          Check & install requirements
        </button>
        <p className="footnote">
          An empty policy makes no domain-conformance claim. Imported snapshots
          retain their actual policy.
        </p>
      </section>
    </div>
  );
}
