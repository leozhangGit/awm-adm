import { useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { Notice } from "./components.tsx";
import type { Adm } from "./types.ts";

export type Deletion = {
  operation_id: string;
  adm_id: string;
  stage: string;
  version: number;
  resume_stage: string | null;
  gateway_pending: number;
  message: string | null;
  created_at_ms: number;
};

export function forgetOutbox(adm: string) {
  try {
    for (const key of Object.keys(sessionStorage))
      if (key.startsWith(`adm-chat-outbox:${adm}:`))
        sessionStorage.removeItem(key);
  } catch {
    /* Browser storage may be disabled. */
  }
}

export function OwnerLifecycle({
  adm,
  onChanged,
}: {
  adm: Adm;
  onChanged: () => void;
}) {
  const [name, setName] = useState(adm.name);
  const [confirm, setConfirm] = useState("");
  const [showDelete, setShowDelete] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const identity = useRef<{ meaning: string; key: string } | null>(null);
  useEffect(() => {
    setName(adm.name);
    setConfirm("");
    identity.current = null;
  }, [adm.id, adm.name]);
  async function perform(action: () => Promise<void>) {
    setBusy(true);
    setError("");
    try {
      await action();
      onChanged();
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel">
      <h2>Model name</h2>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          void perform(async () => {
            await api(`/adms/${adm.id}/name`, {
              method: "PATCH",
              body: { expected_name: adm.name, name },
            });
          });
        }}
      >
        <label htmlFor="owner-model-name">Name</label>
        <input
          id="owner-model-name"
          value={name}
          maxLength={128}
          onChange={(e) => setName(e.target.value)}
          required
        />
        <button
          className="secondary"
          disabled={busy || name === adm.name || !name.trim()}
        >
          Save name
        </button>
      </form>
      <hr />
      <h3>Delete model</h3>
      <p className="muted">
        Permanently remove this model's accepted knowledge, conversations,
        source material, requests and stored results from this installation.
        Shared provider connections and independent models stay available.
        Existing exports and backups are separate copies.
      </p>
      <p className="muted">
        Pending work will stop. Known charges and uncertain provider
        reservations are retained. Deletion does not refund calls or securely
        erase external copies.
      </p>
      {!showDelete ? (
        <button
          className="danger"
          disabled={busy}
          onClick={() => setShowDelete(true)}
        >
          Delete this model…
        </button>
      ) : (
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void perform(async () => {
              const body = {
                expected_revision: adm.revision_id ?? null,
                expected_epoch: adm.policy_epoch ?? null,
                confirm_name: confirm,
                confirm_delete: true,
              };
              const meaning = JSON.stringify({ adm: adm.id, body });
              if (identity.current?.meaning !== meaning)
                identity.current = { meaning, key: crypto.randomUUID() };
              await api<Deletion>(`/adms/${adm.id}`, {
                method: "DELETE",
                body: { ...body, idempotency_key: identity.current.key },
              });
              forgetOutbox(adm.id);
              window.location.hash = "view=adms";
            });
          }}
        >
          <label htmlFor="delete-model-name">
            Type {adm.name} to confirm deletion
          </label>
          <input
            id="delete-model-name"
            autoComplete="off"
            value={confirm}
            onChange={(e) => setConfirm(e.target.value)}
          />
          <div className="buttons">
            <button className="danger" disabled={busy || confirm !== adm.name}>
              Delete {adm.name}
            </button>
            <button
              type="button"
              className="secondary"
              disabled={busy}
              onClick={() => {
                setShowDelete(false);
                setConfirm("");
              }}
            >
              Keep model
            </button>
          </div>
          <p className="footnote">
            If the response is lost, the same submission identity is retained.
            Cleanup progress is available in the model collection after reload.
          </p>
        </form>
      )}
      {error && <Notice error>{error}</Notice>}
    </section>
  );
}

export function PendingDeletions({ onChanged }: { onChanged: () => void }) {
  const [items, setItems] = useState<Deletion[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState("");
  useEffect(() => {
    const controller = new AbortController();
    let running = false;
    async function load() {
      if (running) return;
      running = true;
      try {
        let after = 0;
        const rows: Deletion[] = [];
        // Active cleanup does not repeatedly fetch retained history.
        for (let i = 0; i < 100; i++) {
          const page = await api<{ items: Deletion[]; next_cursor: number }>(
            `/deletions?scope=active&after=${after}&limit=100`,
            { signal: controller.signal },
          );
          rows.push(...page.items);
          after = page.next_cursor;
          if (page.items.length < 100) break;
        }
        if (!controller.signal.aborted) {
          setItems(rows);
          setError("");
        }
      } catch (e) {
        if (!controller.signal.aborted) setError((e as Error).message);
      } finally {
        running = false;
      }
    }
    void load();
    const timer = setInterval(() => void load(), 3000);
    return () => {
      controller.abort();
      clearInterval(timer);
    };
  }, []);
  const active = items.filter((x) => x.stage !== "deleted");
  if (!active.length && !error) return null;
  return (
    <section className="panel" aria-label="Model deletion progress">
      <h2>Deletions in progress</h2>
      {error && <Notice error>{error}</Notice>}
      {active.map((x) => (
        <div key={x.operation_id} className="notice">
          <small>
            Requested {new Date(x.created_at_ms).toLocaleString()} ·{" "}
            {x.operation_id.slice(0, 10)}
          </small>
          <strong>
            {x.stage === "blocked"
              ? "Cleanup needs attention"
              : x.stage === "purging" && x.gateway_pending
                ? "Finishing local and gateway cleanup"
                : "Removing model content"}
          </strong>
          <p>
            {x.stage === "blocked"
              ? x.message
              : "New access and publication are disabled. Provider records are retained until cleanup is safe."}
          </p>
          {x.stage === "blocked" && (
            <button
              className="secondary"
              disabled={!!busy}
              onClick={async () => {
                setBusy(x.operation_id);
                setError("");
                try {
                  const next = await api<Deletion>(
                    `/deletions/${x.operation_id}/retry`,
                    {
                      method: "POST",
                      body: { expected_version: x.version },
                    },
                  );
                  setItems((rows) =>
                    rows.map((row) =>
                      row.operation_id === next.operation_id ? next : row,
                    ),
                  );
                  onChanged();
                } catch (e) {
                  setError((e as Error).message);
                } finally {
                  setBusy("");
                }
              }}
            >
              Retry cleanup
            </button>
          )}
        </div>
      ))}
    </section>
  );
}
