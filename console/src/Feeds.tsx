import { useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { Badge, JsonDetail, JsonEditor, Notice } from "./components.tsx";
import { parseJson } from "./query.ts";
import type { Adm } from "./types.ts";
import { short } from "./types.ts";

type Feed = {
  id: string;
  generation: number;
  enabled: boolean;
  cursor: number;
  backlog: number;
  body: {
    name: string;
    publication: string;
    extractor: string;
    source_ids: string[];
  };
  received: number;
  extracted: number;
  admitted: number;
  unknown_calls: number;
  remaining: Record<string, number>;
  reserved: Record<string, number>;
  counts: Record<string, number>;
  stall_reason: string | null;
};
type Item = {
  seq: number;
  feed: string;
  id: string;
  source_seq: number;
  status: string;
  reason: string | null;
  episode: string | null;
  episode_status?: string;
  receipt_sequence?: number;
};
type Page = {
  feeds: Feed[];
  items: Item[];
  next_cursor: number;
  provider_usage: { unresolved: number };
};
const initial = JSON.stringify(
  {
    name: "",
    source_ids: [],
    enabled: false,
    publication: "review",
    extractor: "local",
    allow_external: false,
    requirements: [],
    after_sequence: 0,
    budget: {
      max_items: 20,
      max_calls: 20,
      max_input_tokens: 640000,
      max_output_tokens: 163840,
      max_work: 60000000,
    },
    max_pending: 4,
    max_failures: 3,
    retry_limit: 2,
    backoff_seconds: 2,
  },
  null,
  2,
);

export function Feeds({
  adm,
  generation,
}: {
  adm: string;
  generation: number;
}) {
  const [page, setPage] = useState<Page | null>(null),
    [after, setAfter] = useState(0);
  const [input, setInput] = useState(initial),
    [coverage, setCoverage] = useState(
      '{"kind":"extend","projection":null,"reason":""}',
    );
  const [error, setError] = useState(""),
    [readError, setReadError] = useState(""),
    [notice, setNotice] = useState("");
  const [previews, setPreviews] = useState<Record<string, unknown>>({});
  const [busy, setBusy] = useState(false),
    [sequence, setSequence] = useState("1");
  const saved = useRef<{
    meaning: string;
    body: Record<string, unknown>;
  } | null>(null);
  const [passId, setPassId] = useState(() => crypto.randomUUID());
  const base = `/adms/${adm}`;
  async function refresh() {
    setPage(await api<Page>(`${base}/feeds?after=${after}&limit=20`));
  }
  useEffect(() => {
    let active = true;
    async function read() {
      try {
        const value = await api<Page>(`${base}/feeds?after=${after}&limit=20`);
        if (active) {
          setPage(value);
          setReadError("");
        }
      } catch (e) {
        if (active) setReadError(String(e));
      }
    }
    void read();
    const timer = setInterval(() => void read(), 2000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [base, after]);
  async function act(action: () => Promise<unknown>, text: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      setNotice(text);
      await refresh();
    } catch (e) {
      setError(String(e));
    } finally {
      setBusy(false);
    }
  }
  async function revision() {
    return (await api<Adm>(base)).revision_id;
  }
  return (
    <section className="panel">
      <div className="section-heading">
        <div>
          <h2>Continuous learning feeds</h2>
          <p className="muted">
            An enabled standing policy processes supplied source versions in
            bounded background steps. Accepted knowledge continues serving
            locally.
          </p>
        </div>
        <Badge>Owner controlled</Badge>
      </div>
      {readError && <Notice error>{readError}</Notice>}
      {error && <Notice error>{error}</Notice>}
      {notice && <Notice>{notice}</Notice>}
      <details>
        <summary>Create a feed</summary>
        <p>
          List permitted source IDs and choose local extraction or an explicit
          extraction connection/version. Review holds each candidate. Checked
          automatic publication requires owner-authored predicate requirements
          in addition to source permission and ordinary admission.
        </p>
        <p>
          Budgets are lifetime reservations for this policy. Pause, restart and
          calendar changes do not replenish them. The feed starts paused unless
          enabled explicitly. Each item reserves three local computation limits.
        </p>
        <JsonEditor
          label="Standing feed policy"
          value={input}
          onChange={setInput}
        />
        <button
          disabled={busy || !generation}
          onClick={() =>
            void act(async () => {
              const body = parseJson(input) as Record<string, unknown>;
              const meaning = JSON.stringify({ body, generation });
              if (saved.current?.meaning !== meaning) {
                saved.current = {
                  meaning,
                  body: {
                    ...body,
                    idempotency_key: crypto.randomUUID(),
                    expected_revision: await revision(),
                    expected_source_generation: generation,
                  },
                };
              }
              return api(base + "/feeds", {
                method: "POST",
                body: saved.current.body,
              });
            }, "Feed policy created.")
          }
        >
          Create feed
        </button>
      </details>
      {page && (
        <>
          <p className="muted">
            Unresolved provider reservations for this ADM:{" "}
            {page.provider_usage.unresolved}. Unsettled usage retains its
            reserved tokens. Intake acknowledgment means received material, not
            accepted facts.
          </p>
          {page.feeds.length === 0 && (
            <Notice>
              No feeds configured. Manual source intake and extraction remain
              available below.
            </Notice>
          )}
          {page.feeds.map((f) => (
            <article className="panel" key={f.id}>
              <div className="section-heading">
                <h3>{f.body.name}</h3>
                <Badge>{f.enabled ? "Enabled" : "Paused"}</Badge>
              </div>
              <p>
                {f.body.source_ids.join(", ")} · {f.body.extractor} ·{" "}
                {f.body.publication} · generation {f.generation}
              </p>
              <p>
                Scanned receipt cursor {f.cursor} · waiting intake {f.backlog} ·
                received {f.received} · extracted {f.extracted} · admitted{" "}
                {f.admitted} · unknown calls {f.unknown_calls} · held/dead
                letter {(f.counts.held || 0) + (f.counts.dead_letter || 0)}
              </p>
              {f.stall_reason && <Notice>{f.stall_reason}</Notice>}
              <div className="actions">
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(
                      async () =>
                        api(`${base}/feeds/${f.id}`, {
                          method: "PUT",
                          body: {
                            expected_generation: f.generation,
                            expected_revision: await revision(),
                            enabled: !f.enabled,
                          },
                        }),
                      f.enabled
                        ? "Feed paused. Other valid interests retain their work."
                        : "Feed resumed within its existing allowance.",
                    )
                  }
                >
                  {f.enabled ? "Pause feed" : "Resume feed"}
                </button>
              </div>
              <JsonDetail
                label="Remaining and reserved allowances"
                value={{
                  remaining: f.remaining,
                  reserved: f.reserved,
                  states: f.counts,
                }}
              />
              <details>
                <summary>Explicit reprocessing</summary>
                <p>
                  Creates a new processing identity and consumes a new item
                  allowance. This is the explicit way to revisit held or
                  uncertain work.
                </p>
                <p>
                  Pass identity: {passId}. Retrying this pass reuses its
                  reservation.
                </p>
                <button
                  disabled={busy}
                  onClick={() => setPassId(crypto.randomUUID())}
                >
                  Start a new reprocessing pass
                </button>
                <label>
                  Source receipt sequence
                  <input
                    type="number"
                    min="1"
                    value={sequence}
                    onChange={(e) => setSequence(e.target.value)}
                  />
                </label>
                <button
                  disabled={busy || !f.enabled}
                  onClick={() =>
                    void act(
                      async () =>
                        api(`${base}/feeds/${f.id}/reprocess`, {
                          method: "POST",
                          body: {
                            idempotency_key: passId,
                            expected_generation: f.generation,
                            source_sequence: Number(sequence),
                          },
                        }),
                      "Explicit reprocessing recorded.",
                    )
                  }
                >
                  Reprocess source version
                </button>
              </details>
            </article>
          ))}
          <h3>Processing history</h3>
          <div className="table-wrap">
            <table>
              <thead>
                <tr>
                  <th>Source</th>
                  <th>State</th>
                  <th>Candidate order</th>
                  <th>Action</th>
                </tr>
              </thead>
              <tbody>
                {page.items.map((item) => (
                  <tr key={item.seq}>
                    <td>
                      #{item.source_seq}
                      <small> · {short(item.feed)}</small>
                    </td>
                    <td>
                      {item.episode_status || item.status}
                      {item.reason && <p>{item.reason}</p>}
                    </td>
                    <td>{item.receipt_sequence ?? "Not received"}</td>
                    <td>
                      {item.episode_status === "awaiting_review" && (
                        <>
                          <button
                            disabled={busy}
                            onClick={() =>
                              void act(async () => {
                                const value = await api<{
                                  claims: unknown;
                                  policy: unknown;
                                  receipt_sequence: number;
                                  result: { preview: unknown };
                                }>(
                                  `${base}/sources/history/episodes/${item.episode}`,
                                );
                                setPreviews((p) => ({
                                  ...p,
                                  [item.id]: {
                                    declarations: value.result.preview,
                                    claims: value.claims,
                                    policy: value.policy,
                                    receipt_sequence: value.receipt_sequence,
                                  },
                                }));
                              }, "Candidate details loaded for review.")
                            }
                          >
                            Inspect candidate
                          </button>
                          {previews[item.id] !== undefined && (
                            <JsonDetail
                              label="Candidate declarations and evidence"
                              value={previews[item.id]}
                            />
                          )}
                          <button
                            disabled={busy || previews[item.id] === undefined}
                            onClick={() =>
                              void act(
                                async () =>
                                  api(
                                    `${base}/sources/episodes/${item.episode}/review`,
                                    {
                                      method: "POST",
                                      body: {
                                        approve: true,
                                        expected_revision: await revision(),
                                      },
                                    },
                                  ),
                                "Review approved; ordinary ordered admission still applies.",
                              )
                            }
                          >
                            Approve reviewed candidate
                          </button>
                        </>
                      )}
                      <JsonDetail label="Processing identity" value={item} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="actions">
            <button disabled={!after} onClick={() => setAfter(0)}>
              First page
            </button>
            <button
              disabled={page.items.length < 20}
              onClick={() => setAfter(page.next_cursor)}
            >
              Next page
            </button>
          </div>
        </>
      )}
      <details>
        <summary>Change finite coverage</summary>
        <p>
          Extend adds bounded cells without changing existing identities. Window
          selects coverage and holds earlier facts outside it; original evidence
          and results remain. Predicate carriers cannot change and retained
          cells cannot be split or merged. Existing feeds need a new policy
          after a source-generation change.
        </p>
        <JsonEditor
          label="Coverage transition"
          value={coverage}
          onChange={setCoverage}
        />
        <button
          disabled={busy || !generation}
          onClick={() =>
            void act(
              async () =>
                api(base + "/sources/coverage", {
                  method: "POST",
                  body: {
                    ...(parseJson(coverage) as Record<string, unknown>),
                    expected_revision: await revision(),
                    expected_generation: generation,
                  },
                }),
              "Coverage transition checked and recorded.",
            )
          }
        >
          Apply checked coverage transition
        </button>
      </details>
    </section>
  );
}
