import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { Badge, Notice } from "./components.tsx";
import type { Adm } from "./types.ts";

type Diagnostics = {
  created_at_ms: number;
  status: Record<string, boolean>;
  storage: { bytes: number; limit_bytes: number };
  instances: {
    adm_id: string;
    storage_bytes: number;
    requests: Record<string, number>;
    source_jobs: Record<string, number>;
    feed_runs: Record<string, number>;
  }[];
};
const count = (states: Record<string, number>, names: string[]) =>
  names.reduce((total, name) => total + (states[name] || 0), 0);
const size = (bytes: number) =>
  bytes >= 1073741824
    ? `${(bytes / 1073741824).toFixed(1)} GiB`
    : `${(bytes / 1048576).toFixed(1)} MiB`;

export function Operations() {
  const [data, setData] = useState<Diagnostics | null>(null);
  const [models, setModels] = useState<Adm[]>([]);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      setBusy(true);
      try {
        const [report, items] = await Promise.all([
          api<Diagnostics>("/operations/diagnostics", { signal: abort.signal }),
          api<{ items: Adm[] }>("/adms", { signal: abort.signal }),
        ]);
        setData(report);
        setModels(items.items);
        setError("");
      } catch (e) {
        if (!abort.signal.aborted) setError((e as Error).message);
      } finally {
        if (!abort.signal.aborted) {
          setBusy(false);
          timer = setTimeout(tick, 10000);
        }
      }
    };
    void tick();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, []);
  return (
    <>
      <div className="page-heading">
        <div>
          <p className="eyebrow">SERVICE STATUS</p>
          <h1>Operations</h1>
          <p className="muted">
            Health, work and storage at a glance. Updates automatically.
          </p>
        </div>
      </div>
      {error && (
        <Notice error>{error} The last available status is shown below.</Notice>
      )}
      {!data ? (
        <Notice>
          {busy ? "Checking service…" : "Service status is unavailable."}
        </Notice>
      ) : (
        <>
          <section className="metrics" aria-label="Service health">
            {(
              [
                [
                  "Model execution",
                  "local_serving",
                  "Accepted models answer through the ADM engine.",
                ],
                [
                  "Background worker",
                  "worker",
                  "Processes learning and supplied material.",
                ],
                [
                  "Provider gateway",
                  "gateway",
                  "Connects to the configured provider.",
                ],
                ["Proof checker", "lean", "Checks requested invariant proofs."],
              ] as const
            ).map(([name, key, note]) => (
              <article className="panel" key={key}>
                <h2>{name}</h2>
                <Badge tone={data.status[key] ? "green" : "amber"}>
                  {data.status[key] ? "Available" : "Unavailable"}
                </Badge>
                <p className="muted">{note}</p>
              </article>
            ))}
          </section>
          <section className="panel">
            <h2>Storage</h2>
            <p>
              <strong>{size(data.storage.bytes)}</strong> used of{" "}
              {size(data.storage.limit_bytes)}.
            </p>
            <meter
              aria-label="Service storage usage"
              min={0}
              max={data.storage.limit_bytes}
              value={data.storage.bytes}
            />
            <p className="muted">
              Model knowledge, evidence, conversations and operational records.
            </p>
          </section>
          <section className="panel">
            <h2>Work by model</h2>
            <p className="muted">
              Current work and retained request outcomes. Open a model’s History
              for its conversations and results.
            </p>
            {!data.instances.length ? (
              <p>No models yet.</p>
            ) : (
              <div
                className="table-scroll work-table-scroll"
                role="region"
                aria-label="Work by model"
                tabIndex={0}
              >
                <table className="work-table">
                  <thead>
                    <tr>
                      <th scope="col">Model</th>
                      <th scope="col">Requests in progress</th>
                      <th scope="col">Waiting for input</th>
                      <th scope="col">Failed requests</th>
                      <th scope="col">Source work in progress</th>
                      <th scope="col">Stored</th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.instances.map((row) => (
                      <tr key={row.adm_id}>
                        <th scope="row">
                          <a
                            href={`#view=adms&adm=${encodeURIComponent(row.adm_id)}&tab=history`}
                          >
                            {models.find((m) => m.id === row.adm_id)?.name ||
                              "Model"}
                          </a>
                        </th>
                        <td>
                          {count(row.requests, [
                            "received",
                            "queued",
                            "evaluating",
                            "waiting_for_learning",
                          ])}
                        </td>
                        <td>{count(row.requests, ["needs_input"])}</td>
                        <td>
                          {count(row.requests, ["failed", "interrupted"])}
                        </td>
                        <td>
                          {count(row.source_jobs, [
                            "received",
                            "queued",
                            "extracting",
                            "running",
                          ]) +
                            count(row.feed_runs, [
                              "received",
                              "queued",
                              "running",
                              "extracting",
                              "projecting",
                            ])}
                        </td>
                        <td>{size(row.storage_bytes)}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
            <p className="footnote">
              Last checked {new Date(data.created_at_ms).toLocaleString()}.
              Provider-call totals and token usage are in{" "}
              <a href="#view=connections">Connections</a>.
            </p>
          </section>
        </>
      )}
    </>
  );
}
