import { useEffect, useState } from "react";
import { api, readJsonFile } from "./api.ts";
import type { Adm, Json } from "./types.ts";

import { OwnerLifecycle } from "./Lifecycle.tsx";
import { Notice } from "./components.tsx";

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
            const value = kind === "import" ? snapshot : undefined;
            if (kind === "import" && !value)
              throw Error("Choose a snapshot file.");
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
  const [mode, setMode] = useState(adm.mode),
    [archive, setArchive] = useState(false);
  useEffect(() => setMode(adm.mode), [adm.mode]);
  return (
    <div className="settings-grid">
      <OwnerLifecycle adm={adm} onChanged={onChanged} />
      <section className="panel">
        <p className="eyebrow">OWNER CONTROLS</p>
        <h2>Learning precedence</h2>
        <p className="muted">
          Both modes enforce the same admission requirements. Switching affects
          future conflict decisions only. Both modes can learn nonconflicting
          knowledge. Work based on the previous model may ask for a fresh
          request after a switch.
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
    </div>
  );
}
