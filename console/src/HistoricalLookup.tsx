import { useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { JsonDetail, Notice, ResultPanel } from "./components.tsx";
import { submissionError } from "./feedback.ts";
import type { Limits, RequestView } from "./types.ts";

type Projection = {
  entities: string[];
  predicates: { symbol: string; unit: string }[];
  cells: {
    effective_from: string;
    effective_to: string | null;
    kind: string;
  }[];
};

/** Explicit typed request, with no interpretation or provider fallback. */
export function HistoricalLookup({
  adm,
  revision,
  limits,
  onHistory,
}: {
  adm: string;
  revision: string;
  limits: Limits;
  onHistory: (id: string) => void;
}) {
  const [profiles, setProfiles] = useState<Projection[]>([]);
  const [entity, setEntity] = useState("");
  const [predicate, setPredicate] = useState("");
  const [time, setTime] = useState("");
  const [readError, setReadError] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [record, setRecord] = useState<RequestView | null>(null);
  const submission = useRef<{ meaning: string; key: string } | null>(null);
  useEffect(() => {
    let current = true;
    setProfiles([]);
    setEntity("");
    setPredicate("");
    api<{ context: { revision_id: string }; projections: Projection[] }>(
      `/adms/${adm}/history-options`,
      {},
    )
      .then((value) => {
        if (current) {
          if (value.context.revision_id !== revision)
            throw Error(
              "Model changed while reading historical choices. Refresh this view.",
            );
          setProfiles(value.projections);
          setReadError("");
        }
      })
      .catch((e) => {
        if (current) setReadError(e.message);
      });
    return () => {
      current = false;
    };
  }, [adm, revision]);
  useEffect(() => {
    if (!record) return;
    let current = true;
    const read = () =>
      void api<RequestView>(`/adms/${adm}/requests/${record.request_id}`)
        .then((value) => {
          if (current) {
            setRecord(value);
            setReadError("");
          }
        })
        .catch((e) => {
          if (current) setReadError(e.message);
        });
    read();
    const timer = ["received", "evaluating"].includes(record.status)
      ? setInterval(read, 1000)
      : undefined;
    return () => {
      current = false;
      clearInterval(timer);
    };
  }, [adm, revision, record?.request_id, record?.status]);
  const relevant = profiles.filter(
    (p) => !entity || p.entities.includes(entity),
  );
  const projection = profiles.length
    ? {
        entities: [...new Set(profiles.flatMap((p) => p.entities))],
        predicates: [
          ...new Map(
            relevant.flatMap((p) => p.predicates).map((p) => [p.symbol, p]),
          ).values(),
        ],
        cells: [
          ...new Map(
            relevant.flatMap((p) => p.cells).map((c) => [JSON.stringify(c), c]),
          ).values(),
        ],
      }
    : null;
  const query = {
    op: "lookup_fact",
    entity_id: entity,
    predicate,
    effective_at: time,
  };
  async function submit() {
    setBusy(true);
    setError("");
    try {
      if (
        !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(time) ||
        Number.isNaN(Date.parse(time)) ||
        new Date(time).toISOString().replace(".000Z", "Z") !== time
      )
        throw Error(
          "Enter a complete valid UTC instant, such as 2026-06-01T00:00:00Z.",
        );
      const meaning = JSON.stringify({ adm, revision, query, limits });
      if (submission.current?.meaning !== meaning)
        submission.current = { meaning, key: crypto.randomUUID() };
      const result = await api<RequestView>(`/adms/${adm}/requests`, {
        method: "POST",
        revision,
        body: {
          idempotency_key: submission.current.key,
          query,
          limits,
          on_gap: "report",
        },
      });
      setRecord(result);
      submission.current = null;
    } catch (e) {
      setError(submissionError(e));
    } finally {
      setBusy(false);
    }
  }
  async function control(action: "cancel" | "retry") {
    if (!record) return;
    setBusy(true);
    setError("");
    try {
      setRecord(
        await api<RequestView>(
          `/adms/${adm}/requests/${record.request_id}/${action}`,
          { method: "POST" },
        ),
      );
    } catch (e) {
      setError(submissionError(e));
    } finally {
      setBusy(false);
    }
  }
  return (
    <section className="panel" aria-label="Historical fact lookup">
      <details>
        <summary>Look up a historical fact · local only</summary>
        <p>
          Select an entity and predicate from accepted history or source
          settings, then enter an exact UTC time. Missing coverage or disputed
          support returns a gap. No provider call is made.
        </p>
        {readError && <Notice error>{readError}</Notice>}
        {error && <Notice error>{error}</Notice>}
        {!projection && (
          <Notice>
            This model has no historical choices yet. Teach it supplied evidence
            or import a snapshot containing historical facts.
          </Notice>
        )}
        {projection && (
          <form
            onSubmit={(event) => {
              event.preventDefault();
              void submit();
            }}
          >
            <div className="form-grid">
              <label>
                Historical entity
                <select
                  value={entity}
                  onChange={(e) => {
                    setEntity(e.target.value);
                    setPredicate("");
                  }}
                >
                  <option value="">Select entity</option>
                  {projection.entities.map((e) => (
                    <option key={e}>{e}</option>
                  ))}
                </select>
              </label>
              <label>
                Historical predicate
                <select
                  value={predicate}
                  onChange={(e) => setPredicate(e.target.value)}
                >
                  <option value="">Select predicate</option>
                  {projection.predicates.map((p) => (
                    <option key={p.symbol} value={p.symbol}>
                      {p.symbol} ({p.unit})
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Historical effective time (UTC)
                <input
                  value={time}
                  onChange={(e) => setTime(e.target.value)}
                  placeholder="2026-06-01T00:00:00Z"
                />
              </label>
            </div>
            <JsonDetail label="Declared time cells" value={projection.cells} />
            <JsonDetail label="Exact local lookup request" value={query} />
            <button
              className="primary"
              disabled={
                busy ||
                !projection.entities.includes(entity) ||
                !projection.predicates.some((p) => p.symbol === predicate) ||
                !time
              }
            >
              Look up fact locally
            </button>
          </form>
        )}
        {record && (
          <>
            <ResultPanel
              request={record}
              busy={busy}
              onCancel={() => void control("cancel")}
              onRetry={() => void control("retry")}
            />
            <button
              className="secondary"
              onClick={() => onHistory(record.request_id)}
            >
              Open historical request details
            </button>
          </>
        )}
      </details>
    </section>
  );
}
