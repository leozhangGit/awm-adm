import { useEffect, useState } from "react";
import { api } from "./api.ts";
import { providerBlock } from "./feedback.ts";
import type { ProviderFailureView } from "./feedback.ts";
import { ProviderFailure } from "./ProviderFailure.tsx";
import { Feeds } from "./Feeds.tsx";
import { Badge, JsonDetail, JsonEditor, Notice } from "./components.tsx";
import { parseJson } from "./query.ts";
import type { Adm } from "./types.ts";
import { pretty, short } from "./types.ts";

type Source = {
  id: string;
  current: boolean;
  content_truncated?: boolean;
  content: string;
  receipt_sequence: number;
  record: {
    source_id: string;
    item_id: string;
    version_id: string;
    media_type: string;
    origin: string;
    content_digest: string;
    received_at_ms: number;
    supersedes_version: string | null;
  };
};
type Claim = {
  status: string;
  reason: string | null;
  excerpt: string;
  evidence_group: string;
  statement_digest: string;
  job_id: string;
  claim: {
    claim_id: string;
    entity_id: string;
    predicate: string;
    value: { kind: string; value: unknown };
    unit: string;
    temporal_scope: {
      effective_from: string | null;
      effective_to: string | null;
      kind: string;
    };
    source: { start_byte: number; end_byte: number; version_id: string };
    assertion_kind: string;
  };
};
type Job = {
  id: string;
  body: { reprocess_id: string | null };
  status: string;
  error: string | null;
  grant_id: string | null;
  provider_failure?: ProviderFailureView | null;
  result: { proposal?: unknown } | null;
};
type Episode = {
  id: string;
  status: string;
  error: string | null;
  receipt_sequence?: number;
  accepted_revision?: string;
  result: { preview: unknown } | null;
  decision?: unknown;
};
type State = {
  more: boolean;
  policy: { generation: number; projection?: unknown; sources?: unknown };
  versions: Source[];
  claims: Claim[];
  jobs: Job[];
  episodes: Episode[];
  revalidations: unknown[];
};
type Connection = {
  provider: string;
  id: string;
  name: string;
  version: number;
  purposes: string[];
  enabled: boolean;
  status: string;
};
const editable = (s: string) =>
  [
    "queued",
    "checking",
    "preparing",
    "awaiting_provider",
    "awaiting_review",
    "approved",
    "validating",
  ].includes(s);

export function Sources({
  adms,
  initialAdm,
}: {
  adms: Adm[];
  initialAdm: string;
}) {
  const [key, setKey] = useState(initialAdm || adms[0]?.id || "");
  return (
    <section>
      <div className="section-heading">
        <div>
          <p className="eyebrow">SUPPLIED KNOWLEDGE</p>
          <h1>Sources & historical facts</h1>
          <p className="muted">
            Keep material, extracted claims and accepted knowledge separate.
          </p>
        </div>
        <label>
          Domain model
          <select value={key} onChange={(e) => setKey(e.target.value)}>
            <option value="">Select a model</option>
            {adms
              .filter((a) => !a.archived)
              .map((a) => (
                <option key={a.id} value={a.id}>
                  {a.name}
                </option>
              ))}
          </select>
        </label>
      </div>
      {key ? (
        <SourceWorkspace key={key} adm={key} />
      ) : (
        <Notice>Create or select a domain model to supply material.</Notice>
      )}
    </section>
  );
}

function SourceWorkspace({ adm }: { adm: string }) {
  const [page, setPage] = useState(0);
  const [fullText, setFullText] = useState<{
    id: string;
    content: string;
  } | null>(null);
  const [data, setData] = useState<State | null>(null),
    [info, setInfo] = useState<Adm | null>(null);
  const [readError, setReadError] = useState("");
  const [providerError, setProviderError] = useState("");
  const [providerSettings, setProviderSettings] = useState<{
    remote_calls_enabled: boolean;
  } | null>(null);
  const [callLimits, setCallLimits] = useState(
    '{"max_input_tokens":32000,"max_output_tokens":4096,"max_duration_ms":60000}',
  );
  const [error, setError] = useState(""),
    [notice, setNotice] = useState(""),
    [busy, setBusy] = useState(false);
  const [policy, setPolicy] = useState('{"projection":null,"sources":[]}');
  const [sourceId, setSourceId] = useState(""),
    [itemId, setItemId] = useState(""),
    [version, setVersion] = useState("v1"),
    [supersedes, setSupersedes] = useState("");
  const [origin, setOrigin] = useState(""),
    [media, setMedia] = useState("text/plain"),
    [content, setContent] = useState("");
  const [selectedSource, setSelectedSource] = useState(""),
    [connection, setConnection] = useState("");
  const [reprocessId, setReprocessId] = useState("");
  const [connections, setConnections] = useState<Connection[]>([]),
    [selectedClaims, setSelectedClaims] = useState<string[]>([]);
  const [queryEntity, setQueryEntity] = useState(""),
    [queryPredicate, setQueryPredicate] = useState(""),
    [queryTime, setQueryTime] = useState("");
  const [request, setRequest] = useState<string | null>(null),
    [answer, setAnswer] = useState<unknown>(null);
  const base = `/adms/${adm}`;
  async function refresh() {
    const [d, a] = await Promise.all([
      api<State>(base + `/sources?page=${page}&limit=20`),
      api<Adm>(base),
    ]);
    setData(d);
    setInfo(a);
  }
  useEffect(() => {
    let active = true;
    const read = async () => {
      try {
        const [d, a] = await Promise.all([
          api<State>(base + `/sources?page=${page}&limit=20`),
          api<Adm>(base),
        ]);
        if (active) {
          setData(d);
          setInfo(a);
          setReadError("");
        }
      } catch (e) {
        if (active) setReadError(String(e));
      }
    };
    void read();
    const timer = setInterval(read, 2000);

    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [base, page]);
  useEffect(() => {
    let active = true;
    async function refreshProvider() {
      try {
        const [c, settings] = await Promise.all([
          api<{ items: Connection[] }>("/connections"),
          api<{ remote_calls_enabled: boolean }>("/learning"),
        ]);
        if (active) {
          setConnections(c.items);
          setProviderSettings(settings);
          setProviderError("");
        }
      } catch (e) {
        if (active) {
          setProviderSettings(null);
          setProviderError((e as Error).message);
        }
      }
    }
    void refreshProvider();
    const timer = setInterval(() => void refreshProvider(), 3000);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, []);
  useEffect(() => {
    if (!request) return;
    let active = true;
    const read = () =>
      api(base + "/requests/" + request)
        .then((v) => {
          if (active) setAnswer(v);
        })
        .catch((e) => {
          if (active) setReadError(String(e));
        });
    void read();
    const timer = setInterval(read, 1500);
    return () => {
      active = false;
      clearInterval(timer);
    };
  }, [base, request]);
  async function act(action: () => Promise<unknown>, message: string) {
    setBusy(true);
    setError("");
    setNotice("");
    try {
      await action();
      await refresh();
      setNotice(message);
    } catch (e) {
      setError((e as Error).message || "The operation could not complete.");
    } finally {
      setBusy(false);
    }
  }
  const source = data?.versions.find((s) => s.id === selectedSource);
  const body = () => ({
    idempotency_key: crypto.randomUUID(),
    expected_revision: info!.revision_id,
    expected_generation: data!.policy.generation,
  });
  async function extract(purpose: "claims" | "schema") {
    if (!source) throw Error("Select a current source version.");
    if (
      reprocessId.trim() &&
      !/^[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}$/.test(reprocessId.trim())
    )
      throw Error(
        "Use an attempt label of up to 128 letters, numbers, dots, underscores, colons or hyphens, starting with a letter or number.",
      );
    const c = connections.find((c) => c.id === connection);
    if (connection) {
      const blocked = providerBlock(c, providerSettings, "extraction");
      if (blocked) throw Error(blocked);
    }
    return api(base + "/sources/jobs", {
      method: "POST",
      body: {
        ...body(),
        source_id: source.record.source_id,
        item_id: source.record.item_id,
        version_id: source.record.version_id,
        reprocess_id: reprocessId.trim() || null,
        purpose,
        extractor: c ? "external" : "local",
        ...(c
          ? {
              connection_id: c.id,
              connection_version: c.version,
              call_limits: parseJson(callLimits),
            }
          : {}),
      },
    });
  }
  const blockedProvider = connection
    ? providerBlock(
        connections.find((c) => c.id === connection),
        providerSettings,
        "extraction",
      )
    : null;
  if (!data || !info)
    return (
      <Notice error={!!(error || readError)}>
        {error || readError || "Loading supplied material…"}
      </Notice>
    );
  return (
    <div className="stack">
      <Feeds adm={adm} generation={data.policy.generation} />
      <div className="actions">
        <span>Source history page {page + 1} (20 records per section)</span>
        <button disabled={!page} onClick={() => setPage(page - 1)}>
          Previous history
        </button>
        <button disabled={!data.more} onClick={() => setPage(page + 1)}>
          Older history
        </button>
      </div>
      {readError && <Notice error>{readError}</Notice>}
      {error && <Notice error>{error}</Notice>}
      {notice && <Notice>{notice}</Notice>}
      <section className="panel">
        <h2>1. Owner source policy</h2>
        <p>
          Declare permitted sources, attribution and evidence groups, then an
          explicit finite projection. A null projection permits schema proposals
          without accepting facts. External extraction also requires source
          disclosure permission and an enabled connection.
        </p>
        <Badge>Generation {data.policy.generation}</Badge>
        <JsonDetail label="Installed source policy" value={data.policy} />
        <details>
          <summary>Install source policy and finite carriers</summary>
          <p>
            Use <code>projection</code> and <code>sources</code>. A projection
            declares a namespace, entities, typed predicates with exact units,
            and ordered disjoint time cells. Source entries declare source_id,
            attribution, evidence_group and allow_external. Changing source
            permissions disputes existing source support. Installed carriers
            remain fixed in this profile.
          </p>
          <JsonEditor
            label="Owner source policy JSON"
            value={policy}
            onChange={setPolicy}
          />
          <button
            disabled={busy}
            onClick={() =>
              void act(
                async () =>
                  api(base + "/sources/policy", {
                    method: "PUT",
                    body: {
                      ...(parseJson(policy) as object),
                      expected_revision: info.revision_id,
                      expected_generation: data.policy.generation,
                    },
                  }),
                "Source policy installed. Review any disputed support.",
              )
            }
          >
            Install policy
          </button>
          <button
            className="secondary"
            onClick={() =>
              setPolicy(
                pretty({
                  projection: data.policy.projection || null,
                  sources: data.policy.sources || [],
                }),
              )
            }
          >
            Load installed policy into editor
          </button>
        </details>
        <p className="muted">
          Independent behavioral requirements remain in Domain models →
          Settings. Extracted assertions cannot modify them.
        </p>
      </section>
      <section className="panel">
        <h2>2. Supply material</h2>
        <p>
          Upload or paste text, Markdown, JSON or JSONL. Receipt time never
          substitutes for effective time. Uploading does not start a provider
          call.
        </p>
        <div className="form-grid">
          {[
            ["Source ID", sourceId, setSourceId],
            ["Item ID", itemId, setItemId],
            ["Version ID", version, setVersion],
            ["Supersedes version (correction only)", supersedes, setSupersedes],
            ["Origin / attribution", origin, setOrigin],
          ].map(([label, value, setter]) => (
            <label key={String(label)}>
              {String(label)}
              <input
                value={String(value)}
                onChange={(e) =>
                  (setter as (s: string) => void)(e.target.value)
                }
              />
            </label>
          ))}
          <label>
            Format
            <select value={media} onChange={(e) => setMedia(e.target.value)}>
              {[
                "text/plain",
                "text/markdown",
                "application/json",
                "application/x-ndjson",
              ].map((t) => (
                <option key={t}>{t}</option>
              ))}
            </select>
          </label>
        </div>
        <label>
          Choose source file
          <input
            type="file"
            accept=".txt,.md,.json,.jsonl,.ndjson"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f)
                void act(async () => {
                  if (f.size > 262144)
                    throw Error("Choose a file at most 256 KiB.");
                  setContent(
                    new TextDecoder("utf-8", {
                      fatal: true,
                      ignoreBOM: true,
                    }).decode(await f.arrayBuffer()),
                  );
                  setOrigin(f.name);
                  if (!itemId)
                    setItemId(f.name.replace(/[^A-Za-z0-9_.:-]/g, "_"));
                  setMedia(
                    f.name.endsWith(".json")
                      ? "application/json"
                      : /\.(jsonl|ndjson)$/.test(f.name)
                        ? "application/x-ndjson"
                        : f.name.endsWith(".md")
                          ? "text/markdown"
                          : "text/plain",
                  );
                }, "File loaded. Review its identity and submit.");
            }}
          />
        </label>
        <JsonEditor
          label="Source content (preserved exactly)"
          value={content}
          onChange={setContent}
        />
        <button
          className="primary"
          disabled={busy || !content || !sourceId || !itemId || !origin}
          onClick={() =>
            void act(
              () =>
                api(base + "/sources/batches", {
                  method: "POST",
                  body: {
                    idempotency_key: crypto.randomUUID(),
                    items: [
                      {
                        source_id: sourceId,
                        item_id: itemId,
                        version_id: version,
                        media_type: media,
                        content,
                        origin,
                        supersedes_version: supersedes || null,
                      },
                    ],
                  },
                }),
              "Immutable source version stored.",
            )
          }
        >
          Store source version
        </button>
      </section>
      <section className="panel">
        <h2>3. Extract and inspect</h2>
        <label>
          Stored version
          <select
            value={selectedSource}
            onChange={(e) => setSelectedSource(e.target.value)}
          >
            <option value="">Select material</option>
            {data.versions.map((s) => (
              <option key={s.id} value={s.id}>
                {s.record.source_id} / {s.record.item_id} /{" "}
                {s.record.version_id}
                {s.current ? "" : " · superseded"}
              </option>
            ))}
          </select>
        </label>
        {source && (
          <>
            <p>
              {source.record.origin} · received{" "}
              {new Date(source.record.received_at_ms).toLocaleString()} ·
              receipt #{source.receipt_sequence} · digest{" "}
              {short(source.record.content_digest)}
            </p>
            <details>
              <summary>Original source text</summary>
              <pre>
                {fullText?.id === source.id ? fullText.content : source.content}
              </pre>
              {source.content_truncated && fullText?.id !== source.id && (
                <button
                  onClick={() =>
                    void api<{ content: string }>(
                      base + "/sources/history/versions/" + source.id,
                    )
                      .then((v) =>
                        setFullText({ id: source.id, content: v.content }),
                      )
                      .catch((e) => setError(String(e)))
                  }
                >
                  Load complete original text
                </button>
              )}
            </details>
          </>
        )}
        <label>
          Extraction method
          <select
            value={connection}
            onChange={(e) => setConnection(e.target.value)}
          >
            <option value="">Local structured extraction</option>
            {connections
              .filter((c) => c.purposes.includes("extraction"))
              .map((c) => (
                <option key={c.id} value={c.id}>
                  {c.name} · {c.status}
                </option>
              ))}
          </select>
        </label>
        {connection && (
          <>
            {providerError && <Notice error>{providerError}</Notice>}
            {providerSettings && (
              <p className="muted">
                Installation remote calls:{" "}
                <strong>
                  {providerSettings.remote_calls_enabled
                    ? "allowed"
                    : "disabled"}
                </strong>
                . Source disclosure permission is also required.
              </p>
            )}
            {blockedProvider && (
              <Notice>
                {blockedProvider}{" "}
                <a href="#view=connections">Open Connections</a>
              </Notice>
            )}
            <JsonEditor
              label="Extraction call limits"
              value={callLimits}
              onChange={setCallLimits}
              rows={4}
            />
          </>
        )}
        <p className="muted">
          Local extraction accepts fact objects in JSON/JSONL, or one{" "}
          <code>fact &#123;…&#125;</code> line in text/Markdown. Prose needs an
          explicit provider proposal. No universal rules are inferred. External
          extraction makes at most one bounded call under shared quotas.
        </p>
        <details>
          <summary>Run a new extraction attempt</summary>
          <p className="muted">
            An unchanged submission returns the existing job. To explicitly try
            again, enter a new attempt label below, then click Extract claims.
            This can spend another provider call using the selected connection
            and displayed limits. Previous outcomes and unsettled reservations
            remain in history. Keep the same label if the submission response is
            lost; changing it can create another call.
          </p>
          <label>
            New attempt label (optional)
            <input
              value={reprocessId}
              onChange={(e) => setReprocessId(e.target.value)}
              maxLength={128}
              placeholder="e.g. extraction-retry-1"
              disabled={busy}
            />
          </label>
          <p className="muted">
            Leave blank for the original attempt. Reusing a label with the same
            source, policy, method and limits returns that attempt, including
            after a page reload. It does not retry automatically.
          </p>
        </details>
        <button
          disabled={busy || !source?.current || !!blockedProvider}
          onClick={() =>
            void act(
              () => extract("claims"),
              "Extraction queued; claims remain unaccepted.",
            )
          }
        >
          Extract claims
        </button>{" "}
        <button
          className="secondary"
          disabled={busy || !source?.current || !!blockedProvider}
          onClick={() =>
            void act(
              () => extract("schema"),
              "Schema proposal queued; installation requires owner review.",
            )
          }
        >
          Propose finite schema
        </button>
        {data.jobs.map((j) => (
          <div className="list-row" key={j.id}>
            <Badge>{j.status}</Badge> {short(j.id)}{" "}
            {j.body.reprocess_id && (
              <span> · attempt {j.body.reprocess_id}</span>
            )}
            {j.error && !j.provider_failure && <span>{j.error}</span>}
            {j.grant_id && <span> · provider grant {short(j.grant_id)}</span>}
            <ProviderFailure failure={j.provider_failure} />
            {j.result?.proposal !== undefined && (
              <>
                <JsonDetail
                  label="Unaccepted schema proposal"
                  value={j.result.proposal}
                />
                <button
                  className="secondary"
                  onClick={() =>
                    setPolicy(
                      pretty({
                        projection: j.result!.proposal,
                        sources: data.policy.sources || [],
                      }),
                    )
                  }
                >
                  Copy proposal to owner editor
                </button>
              </>
            )}
            {editable(j.status) && (
              <button
                className="secondary"
                onClick={() =>
                  void act(
                    () =>
                      api(base + `/sources/jobs/${j.id}/cancel`, {
                        method: "POST",
                      }),
                    "Job cancelled.",
                  )
                }
              >
                Cancel extraction
              </button>
            )}
          </div>
        ))}
        {data.claims.map((row) => {
          const c = row.claim,
            t = c.temporal_scope;
          return (
            <article className="panel" key={c.claim_id}>
              <label>
                <input
                  type="checkbox"
                  disabled={row.status !== "candidate"}
                  checked={selectedClaims.includes(c.claim_id)}
                  onChange={(e) =>
                    setSelectedClaims(
                      e.target.checked
                        ? [...selectedClaims, c.claim_id]
                        : selectedClaims.filter((x) => x !== c.claim_id),
                    )
                  }
                />{" "}
                {c.entity_id} · {c.predicate} = {String(c.value.value)} {c.unit}
              </label>
              <Badge tone={row.status === "candidate" ? "amber" : "neutral"}>
                {row.status}
              </Badge>
              <p>
                {t.kind}: {t.effective_from || "unknown"} →{" "}
                {t.effective_to || "unbounded / point"} · {c.assertion_kind}
              </p>
              <blockquote>{row.excerpt}</blockquote>
              <p className="muted">
                Version {c.source.version_id}, UTF-8 bytes [
                {c.source.start_byte}, {c.source.end_byte}). Evidence group{" "}
                {row.evidence_group || "unassigned"}; statement{" "}
                {short(row.statement_digest)}. Repeated statements do not count
                as independent corroboration.
              </p>
              {row.reason && <Notice>{row.reason}</Notice>}
              <JsonDetail label="Claim provenance" value={row} />
            </article>
          );
        })}
        <button
          className="primary"
          disabled={busy || !selectedClaims.length}
          onClick={() =>
            void act(async () => {
              await api(base + "/sources/episodes", {
                method: "POST",
                body: { ...body(), claim_ids: selectedClaims },
              });
              setSelectedClaims([]);
            }, "Projection episode queued for checking and review.")
          }
        >
          Build selected claims into a candidate
        </button>
      </section>
      <section className="panel">
        <h2>4. Review projection candidates</h2>
        <p>
          Receipt priority is shared with all other learning candidates. Earlier
          unresolved reviews hold later publication. Approval binds the current
          model; ordinary conflict mode and independent requirements still
          apply.
        </p>
        {data.episodes.length === 0 && (
          <p className="muted">No projection episodes yet.</p>
        )}
        {data.episodes.map((e) => (
          <article className="panel" key={e.id}>
            <h3>Projection {short(e.id)}</h3>
            <Badge>{e.status}</Badge> Arrival #{e.receipt_sequence || "pending"}
            {e.error && <Notice error>{e.error}</Notice>}
            <JsonDetail
              label="Candidate declarations"
              value={e.result?.preview}
            />
            {e.decision !== undefined && (
              <JsonDetail label="Admission decision" value={e.decision} />
            )}
            <p>
              {e.accepted_revision && (
                <>Accepted revision {short(e.accepted_revision)}</>
              )}
            </p>
            {e.status === "awaiting_review" && (
              <>
                <button
                  className="primary"
                  disabled={busy}
                  onClick={() =>
                    void act(
                      () =>
                        api(base + `/sources/episodes/${e.id}/review`, {
                          method: "POST",
                          body: {
                            expected_revision: info.revision_id,
                            approve: true,
                          },
                        }),
                      "Approved for local admission checks.",
                    )
                  }
                >
                  Approve for admission
                </button>{" "}
                <button
                  disabled={busy}
                  onClick={() =>
                    void act(
                      () =>
                        api(base + `/sources/episodes/${e.id}/review`, {
                          method: "POST",
                          body: {
                            expected_revision: info.revision_id,
                            approve: false,
                          },
                        }),
                      "Candidate rejected.",
                    )
                  }
                >
                  Reject
                </button>
              </>
            )}
            {editable(e.status) && (
              <button
                className="secondary"
                disabled={busy}
                onClick={() =>
                  void act(
                    () =>
                      api(base + `/sources/episodes/${e.id}/cancel`, {
                        method: "POST",
                      }),
                    "Projection cancelled.",
                  )
                }
              >
                Cancel projection
              </button>
            )}
          </article>
        ))}
        <JsonDetail
          label="Support revalidation holds"
          value={data.revalidations}
        />
      </section>
      <section className="panel">
        <h2>5. Query accepted historical facts</h2>
        <p>
          These requests run locally and appear in model history. Missing
          coverage and disputed support return an explicit unknown / needs-input
          result.
        </p>
        <div className="form-grid">
          <label>
            Entity
            <input
              value={queryEntity}
              onChange={(e) => setQueryEntity(e.target.value)}
            />
          </label>
          <label>
            Predicate
            <input
              value={queryPredicate}
              onChange={(e) => setQueryPredicate(e.target.value)}
            />
          </label>
          <label>
            Effective time (UTC)
            <input
              placeholder="YYYY-MM-DDT00:00:00Z"
              value={queryTime}
              onChange={(e) => setQueryTime(e.target.value)}
            />
          </label>
        </div>
        <button
          disabled={busy || !queryEntity || !queryPredicate || !queryTime}
          onClick={() =>
            void act(async () => {
              const r = await api<{ request_id: string }>(base + "/requests", {
                method: "POST",
                body: {
                  idempotency_key: crypto.randomUUID(),
                  query: {
                    op: "lookup_fact",
                    entity_id: queryEntity,
                    predicate: queryPredicate,
                    effective_at: queryTime,
                  },
                },
              });
              setRequest(r.request_id);
            }, "Local fact request submitted.")
          }
        >
          Look up fact locally
        </button>
        {answer !== null && (
          <JsonDetail label="Bound local request and result" value={answer} />
        )}
      </section>
    </div>
  );
}
