import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { Badge, Notice } from "./components.tsx";
import type { Adm, Model } from "./types.ts";

type Entry = {
  id: string;
  name: string;
  label?: string;
  kind: string;
  category: string;
  description: string;
  excerpt?: string;
  evidence?: {
    id: string;
    source: string;
    kind: string;
    description: string;
  }[];
};
type Page = {
  items: Entry[];
  next_cursor: number | null;
  total: number;
  revision_id: string;
};
export function Knowledge({ adm, model }: { adm: Adm; model: Model }) {
  const [query, setQuery] = useState("");
  const [kind, setKind] = useState("");
  const [page, setPage] = useState<Page | null>(null);
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const path = `/adms/${adm.id}/knowledge?query=${encodeURIComponent(query)}&kind=${encodeURIComponent(kind)}&limit=30`;
  useEffect(() => {
    const abort = new AbortController();
    const timer = setTimeout(() => {
      setBusy(true);
      api<Page>(path, { signal: abort.signal })
        .then((value) => {
          setPage(value);
          setError("");
        })
        .catch((e) => {
          if (!abort.signal.aborted) setError(e.message);
        })
        .finally(() => {
          if (!abort.signal.aborted) setBusy(false);
        });
    }, 180);
    return () => {
      clearTimeout(timer);
      abort.abort();
    };
  }, [path, model.revision_id]);
  return (
    <section className="panel">
      <div className="section-title">
        <div>
          <p className="eyebrow">ACCEPTED KNOWLEDGE</p>
          <h2>Model & evidence</h2>
        </div>
        {page && <Badge>{page.total} matches</Badge>}
      </div>
      <div className="two-columns">
        <label>
          Search knowledge
          <input
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            placeholder="A name, rule, unit or source…"
            maxLength={256}
          />
        </label>
        <label>
          Show
          <select value={kind} onChange={(e) => setKind(e.target.value)}>
            <option value="">All knowledge</option>
            <option value="declaration">Declarations</option>
            <option value="evidence">Evidence</option>
          </select>
        </label>
      </div>
      {error && <Notice error>{error}</Notice>}
      {busy && <p role="status">Searching…</p>}
      {page?.items.map((item) => (
        <article className="knowledge-entry" key={item.id}>
          <div className="section-title">
            <h3>{item.label || item.name}</h3>
            <Badge>{item.kind}</Badge>
          </div>
          <p className="chat-prose">{item.description}</p>
          {Boolean(item.evidence?.length) && (
            <ul className="knowledge-support">
              {item.evidence?.map((e) => (
                <li key={e.id}>
                  <strong>{e.source}</strong> — {e.description}
                </li>
              ))}
            </ul>
          )}
          {item.excerpt && (
            <blockquote className="chat-prose">{item.excerpt}</blockquote>
          )}
        </article>
      ))}
      {!busy && page && !page.items.length && (
        <p className="empty">
          {query || kind
            ? "No accepted knowledge matches this search."
            : "This model is empty. Teach it a rule or supply material to begin."}
        </p>
      )}
      {page?.next_cursor != null && (
        <button
          disabled={busy}
          onClick={async () => {
            setBusy(true);
            try {
              const next = await api<Page>(
                path +
                  `&after=${page.next_cursor}&revision=${encodeURIComponent(page.revision_id)}`,
              );
              setPage({ ...next, items: [...page.items, ...next.items] });
            } catch (e) {
              setError((e as Error).message);
            } finally {
              setBusy(false);
            }
          }}
        >
          Load more
        </button>
      )}
      <p className="footnote">
        These are the model’s current accepted declarations and supporting
        evidence. A recorded source does not establish external truth.
      </p>
    </section>
  );
}
