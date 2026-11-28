import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { Notice } from "./components.tsx";
import { settingsDraft, settingsValues } from "./serviceSettings.ts";
import type { ServiceSettingsReply, SettingsDraft } from "./serviceSettings.ts";

export function ServiceSettings() {
  const [saved, setSaved] = useState<ServiceSettingsReply | null>(null);
  const [draft, setDraft] = useState<SettingsDraft | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  function accept(value: ServiceSettingsReply) {
    setSaved(value);
    setDraft(settingsDraft(value.values));
  }
  useEffect(() => {
    const abort = new AbortController();
    api<ServiceSettingsReply>("/settings", { signal: abort.signal })
      .then(accept)
      .catch((e: Error) => {
        if (!abort.signal.aborted) setError(e.message);
      });
    return () => abort.abort();
  }, []);
  async function reload() {
    setBusy(true);
    setError("");
    setMessage("");
    try {
      accept(await api<ServiceSettingsReply>("/settings"));
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  async function save() {
    if (!saved || !draft || busy) return;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      accept(
        await api<ServiceSettingsReply>("/settings", {
          method: "PUT",
          body: {
            expected_revision: saved.revision,
            values: settingsValues(draft),
          },
        }),
      );
      setMessage(
        "Settings saved. New work will use these limits; no restart is needed.",
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const change = (key: keyof SettingsDraft, value: string) => {
    setDraft((old) => old && { ...old, [key]: value });
    setMessage("");
  };
  return (
    <>
      <header className="page-heading">
        <div>
          <p className="eyebrow">SERVICE CONFIGURATION</p>
          <h1>Settings</h1>
          <p>Shared limits for this installation and all its models.</p>
        </div>
      </header>
      {error && <Notice error>{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      <form
        className="panel"
        onSubmit={(event) => {
          event.preventDefault();
          void save();
        }}
      >
        <h2>Provider calls</h2>
        <p>
          One policy for Ask, Teach and other provider work. These are per-call
          ceilings, not a spending allowance. Tasks and feeds retain their own
          bounded call counts.
        </p>
        {draft ? (
          <>
            <div className="two-columns">
              <label>
                Input reservation ceiling
                <input
                  type="number"
                  min="1"
                  max="1050000"
                  step="1"
                  value={draft.input}
                  disabled={busy}
                  onChange={(e) => change("input", e.target.value)}
                />
                <small>
                  Conservative input units per call, measured from the complete
                  request. These are not reported tokenizer usage.
                </small>
              </label>
              <label>
                Output token ceiling
                <input
                  type="number"
                  min="1"
                  max="100000"
                  step="1"
                  value={draft.output}
                  disabled={busy}
                  onChange={(e) => change("output", e.target.value)}
                />
                <small>
                  Maximum output tokens requested per call. The provider must
                  support the selected limit.
                </small>
              </label>
            </div>
            <label>
              Provider timeout (seconds)
              <input
                type="number"
                min="0.001"
                max="600"
                step="0.001"
                value={draft.seconds}
                disabled={busy}
                onChange={(e) => change("seconds", e.target.value)}
              />
              <small>
                360 seconds is 6 minutes. Queue time and task completion are
                bounded separately.
              </small>
            </label>
            <h2>Model capacity</h2>
            <label>
              Predicate cap per model
              <input
                type="number"
                min="1"
                max="65536"
                step="1"
                value={draft.predicates}
                disabled={busy}
                onChange={(e) => change("predicates", e.target.value)}
              />
              <small>
                Up to 65,536 distinct properties in a model’s temporal evidence
                catalog. Smaller per-request and storage limits still apply.
              </small>
            </label>
            <p>
              Saved settings persist across restarts and apply to new work.
              Running tasks keep their captured limits. Lowering the predicate
              cap does not remove existing knowledge; it restricts further
              catalog growth.
            </p>
          </>
        ) : (
          <p>Loading settings…</p>
        )}
        <div className="actions">
          <button className="primary" type="submit" disabled={!draft || busy}>
            {busy ? "Saving…" : "Save settings"}
          </button>
          <button type="button" disabled={busy} onClick={() => void reload()}>
            Reload saved settings
          </button>
        </div>
      </form>
    </>
  );
}
