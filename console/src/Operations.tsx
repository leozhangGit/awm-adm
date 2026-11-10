import { useEffect, useState } from "react";
import { api, download } from "./api.ts";
import { JsonDetail, Notice } from "./components.tsx";

type Diagnostics = {
  created_at_ms: number;
  storage: { bytes: number; limit_bytes: number };
  provider: {
    accounted_current_window: {
      calls: number;
      unresolved: number;
      input_tokens: number;
      output_tokens: number;
    };
  };
  instances: {
    adm_id: string;
    storage_bytes: number;
    requests: Record<string, number>;
    source_jobs: Record<string, number>;
    feed_runs: Record<string, number>;
  }[];
  compute: Record<string, unknown>;
  retention: unknown;
};

export function Operations() {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  async function refresh() {
    setBusy(true);
    try {
      setData(await api<Diagnostics>("/operations/diagnostics"));
      setError("");
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  useEffect(() => {
    void refresh();
  }, []);
  const mib = (n: number) => (n / 1048576).toFixed(1);
  return (
    <>
      <section className="panel">
        <h2>Service operations</h2>
        <p>
          Inspect storage, queued work and provider accounting. Reports omit
          source text, queries, model content and credentials.
        </p>
        <div className="actions">
          <button
            className="secondary"
            disabled={busy}
            onClick={() => void refresh()}
          >
            {busy ? "Refreshing…" : "Refresh diagnostics"}
          </button>
          <button
            className="secondary"
            disabled={!data || busy || !!error}
            onClick={() => data && download("awm-adm-diagnostics.json", data)}
          >
            Download diagnostic report
          </button>
        </div>
        {error && <Notice error>{error}</Notice>}
        {data && (
          <>
            <p>Sample: {new Date(data.created_at_ms).toLocaleString()}</p>
            <p>
              <strong>{mib(data.storage.bytes)} MiB stored</strong> of{" "}
              {mib(data.storage.limit_bytes)} MiB configured. Compare saved
              reports to observe growth.
            </p>
            <p>
              Provider window: {data.provider.accounted_current_window.calls}{" "}
              accounted calls;{" "}
              {data.provider.accounted_current_window.unresolved} unresolved
              reservations. Unknown usage remains reserved across quota windows.
            </p>
            <JsonDetail
              label="Queues and retained rows by ADM"
              value={data.instances}
            />
            <JsonDetail
              label="Local compute timings and work allowances"
              value={data.compute}
            />
            <JsonDetail label="Retention preview" value={data.retention} />
          </>
        )}
      </section>
      <section className="panel">
        <h2>Backup and recovery</h2>
        <p>
          A service backup captures all ADMs and the gateway ledger together.
          Stop the three services before running the offline operations command.
          A model snapshot creates an independent model and does not restore
          service work.
        </p>
        <pre>{`docker compose stop\ndocker compose run --rm --no-deps operations backup \\\n  --app-data /var/lib/awm-adm \\\n  --gateway-data /var/lib/awm-gateway \\\n  --output /backups/my-backup\ndocker compose up -d --wait`}</pre>
        <p>
          Create the owner-only <code>.local/backups</code> directory first.
          Keep the gateway master key, configuration and service tokens
          separately secured. Recovery uses a new destination, disables remote
          calls, pauses feeds and revokes saved sessions and scoped tokens.
          Follow <code>docs/OPERATIONS.md</code> before restoring.
        </p>
      </section>
      <section className="panel">
        <h2>Retention</h2>
        <p>
          Evidence, model revisions, results, private drafts, dispatch records
          and idempotency identities remain retained within finite storage
          limits. Age settings are review thresholds. No automatic deletion
          runs.
        </p>
        <p>
          Owners can prune an event prefix through the API. Readers behind that
          prefix must reload current resources and resume at the reported
          cursor. Pruning events does not delete source evidence or request
          results.
        </p>
      </section>
    </>
  );
}
