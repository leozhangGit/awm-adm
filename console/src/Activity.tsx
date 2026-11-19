import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { Badge, Notice } from "./components.tsx";

type Item = {
  id: string;
  kind: string;
  title: string | null;
  status: string;
  origin: string;
  created_at_ms: number | null;
  summary: string | null;
};
type Page = {
  items: Item[];
  next_cursor: string | null;
  undated_legacy_items: number;
};
const names: Record<string, string> = {
  ask: "Ask",
  teach: "Teach",
  request: "Model request",
  learning: "Learning",
  extraction: "Source extraction",
  source_admission: "Source admission",
  source_intake: "Source intake",
};
export function Activity({ adm }: { adm: string }) {
  const [start, setStart] = useState("");
  const [kind, setKind] = useState("");
  const [origin, setOrigin] = useState("");
  const [end, setEnd] = useState("");
  const [query, setQuery] = useState("");
  const [refresh, setRefresh] = useState(0);
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/adms/${adm}/activity?limit=30${query}`;
  useEffect(() => {
    const abort = new AbortController();
    setBusy(true);
    api<Page>(path, { signal: abort.signal })
      .then((result) => {
        setPage(result);
        setError("");
      })
      .catch((e) => {
        if (!abort.signal.aborted) setError(e.message);
      })
      .finally(() => {
        if (!abort.signal.aborted) setBusy(false);
      });
    return () => abort.abort();
  }, [path, refresh]);
  function filter() {
    if (start && end && new Date(start) >= new Date(end)) {
      setError("Choose an end time after the start.");
      return;
    }
    setQuery(
      (start ? `&start=${new Date(start).getTime()}` : "") +
        (end ? `&end=${new Date(end).getTime()}` : "") +
        (kind ? `&kind=${kind}` : "") +
        (origin ? `&origin=${origin}` : ""),
    );
    setRefresh((v) => v + 1);
  }
  return (
    <section className="panel">
      <p className="eyebrow">MODEL ACTIVITY</p>
      <h2>History</h2>
      <p>
        Ask, Teach and API activity, with related processing grouped under its
        request.
      </p>
      <form
        onSubmit={(e) => {
          e.preventDefault();
          filter();
        }}
      >
        <div className="two-columns">
          <label>
            From
            <input
              type="datetime-local"
              value={start}
              onChange={(e) => setStart(e.target.value)}
            />
          </label>
          <label>
            Until
            <input
              type="datetime-local"
              value={end}
              onChange={(e) => setEnd(e.target.value)}
            />
          </label>
        </div>
        <div className="two-columns">
          <label>
            Activity
            <select value={kind} onChange={(e) => setKind(e.target.value)}>
              <option value="">All activity</option>
              {Object.entries(names).map(([id, label]) => (
                <option key={id} value={id}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label>
            Origin
            <select value={origin} onChange={(e) => setOrigin(e.target.value)}>
              <option value="">All origins</option>
              <option value="console">Console</option>
              <option value="api">API</option>
              <option value="legacy_chat">Earlier conversations</option>
            </select>
          </label>
        </div>
        <p className="footnote">
          Times use {Intl.DateTimeFormat().resolvedOptions().timeZone}. The end
          time is excluded.
        </p>
        <button disabled={busy}>Show history</button>
      </form>
      {error && <Notice error>{error}</Notice>}
      {busy && <p role="status">Loading history…</p>}
      {!busy && page && !page.items.length && (
        <p className="empty">No activity in this time range.</p>
      )}
      {page?.items.map((item) => (
        <article className="knowledge-entry" key={item.id}>
          <div className="section-title">
            <h3>{names[item.kind] || item.kind.replaceAll("_", " ")}</h3>
            <Badge>{item.status.replaceAll("_", " ")}</Badge>
          </div>
          <small>
            {item.created_at_ms
              ? new Date(item.created_at_ms).toLocaleString()
              : "Time not recorded"}{" "}
            ·{" "}
            {item.origin === "api"
              ? "API"
              : item.origin === "console"
                ? "Console"
                : "Earlier conversation"}
          </small>
          <p className="chat-prose">{item.title}</p>
          {item.summary && <p className="chat-prose">{item.summary}</p>}
        </article>
      ))}
      {page?.next_cursor && (
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const next = await api<Page>(
                path + `&after=${encodeURIComponent(page.next_cursor!)}`,
              );
              setPage({ ...next, items: [...page.items, ...next.items] });
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Load older activity
        </button>
      )}
      {Boolean(page?.undated_legacy_items) && (
        <p className="footnote">
          {page!.undated_legacy_items} earlier source records have no recorded
          time. They appear when no time range is selected.
        </p>
      )}
    </section>
  );
}
