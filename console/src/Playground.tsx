import { useEffect, useMemo, useRef, useState } from "react";
import type { Json, Limits, Model, RequestView } from "./types.ts";
import { pretty, short } from "./types.ts";
import { api } from "./api.ts";
import { submissionError } from "./feedback.ts";
import { callQuery, initial, parseJson, planQuery, resolve } from "./query.ts";
import {
  JsonDetail,
  JsonEditor,
  Notice,
  ResultPanel,
  ValueField,
} from "./components.tsx";

export function Playground({
  adm,
  model,
  limits,
  requestId,
  onRequest,
  refresh,
}: {
  adm: string;
  model: Model;
  limits: Limits;
  requestId: string;
  onRequest: (id: string) => void;
  refresh: number;
}) {
  const [op, setOp] = useState("capabilities"),
    [editor, setEditor] = useState(false),
    [symbol, setSymbol] = useState("");
  const [args, setArgs] = useState<Record<string, Json>>({}),
    [state, setState] = useState<Json>(null);
  const [selection, setSelection] = useState<"all" | "explicit">("all"),
    [actions, setActions] = useState<string[]>([]),
    [depth, setDepth] = useState("");
  const [raw, setRaw] = useState('{"op":"capabilities"}'),
    [certificate, setCertificate] = useState("{}"),
    [backend, setBackend] = useState("lean"),
    [explainId, setExplainId] = useState("");
  const [budget, setBudget] = useState(limits),
    [error, setError] = useState(""),
    [readError, setReadError] = useState(""),
    [busy, setBusy] = useState(false),
    [record, setRecord] = useState<RequestView | null>(null);
  const submission = useRef<{ meaning: string; key: string } | null>(null);
  const decls = model.declarations;
  const choices = useMemo(
    () =>
      Object.entries(decls).filter(([, d]) => {
        if (op === "find_plan") return d.kind === "goal";
        if (op === "evaluate") return d.kind === "function";
        if (op !== "check_claim" || d.kind !== "function" || !d.returns)
          return false;
        try {
          return resolve(d.returns, decls).kind === "bool";
        } catch {
          // Bounded guided forms can abstain; the JSON editor stays available.
          return false;
        }
      }),
    [decls, op],
  );
  const validSymbol = choices.some(([name]) => name === symbol);
  function choose(next: string) {
    setSymbol(next);
    setError("");
    setActions([]);
    try {
      const d = decls[next];
      if (!d) return;
      if (op === "find_plan") setState(initial(d.state!, decls));
      else
        setArgs(
          Object.fromEntries(
            Object.entries(d.params || {}).map(([k, t]) => [
              k,
              initial(t, decls),
            ]),
          ),
        );
    } catch (e) {
      setSymbol("");
      setError((e as Error).message);
    }
  }
  useEffect(() => {
    choose(choices[0]?.[0] || "");
  }, [choices]); // Model-driven choices, never fixture-specific rules.
  useEffect(() => {
    if (!requestId) {
      setRecord(null);
      return;
    }
    const controller = new AbortController();
    api<RequestView>(`/adms/${adm}/requests/${requestId}`, {
      signal: controller.signal,
    })
      .then((value) => {
        setRecord(value);
        setReadError("");
      })
      .catch((e) => {
        if (!controller.signal.aborted) setReadError(e.message);
      });
    return () => controller.abort();
  }, [adm, requestId, refresh]);
  let query: Json = { op: "capabilities" },
    queryError = "";
  try {
    if (editor) query = parseJson(raw);
    else if (op === "evaluate" || op === "check_claim") {
      if (!validSymbol)
        throw Error(
          "This model has no matching functions. Try a different operation or JSON.",
        );
      query = callQuery(op, symbol, decls[symbol], args);
    } else if (op === "find_plan") {
      if (!validSymbol)
        throw Error(
          "This model has no goals yet. Import a model to plan with it.",
        );
      query = planQuery(symbol, state, selection, actions, depth);
    } else if (op === "check_certificate")
      query = { op, certificate: parseJson(certificate), backend };
    else if (op === "explain") query = { op, result_id: explainId };
  } catch (e) {
    queryError = (e as Error).message;
  }
  const transitions = Object.entries(decls).filter(
    ([s, d]) =>
      d.kind === "transition" &&
      s.slice(0, s.lastIndexOf(".")) ===
        symbol.slice(0, symbol.lastIndexOf(".")),
  );
  async function submit() {
    if (queryError) return;
    setBusy(true);
    setError("");
    const meaning = JSON.stringify({
      query,
      limits: budget,
      revision: model.revision_id,
    });
    if (submission.current?.meaning !== meaning)
      submission.current = { meaning, key: crypto.randomUUID() };
    try {
      const result = await api<RequestView>(`/adms/${adm}/requests`, {
        method: "POST",
        body: {
          idempotency_key: submission.current.key,
          query,
          limits: budget,
          on_gap: "report",
        },
        revision: model.revision_id,
      });
      setRecord(result);
      onRequest(result.request_id);
      submission.current = null;
    } catch (e) {
      setError(submissionError(e));
    } finally {
      setBusy(false);
    }
  }
  async function control(action: string) {
    setBusy(true);
    setError("");
    try {
      setRecord(
        await api<RequestView>(`/adms/${adm}/requests/${requestId}/${action}`, {
          method: "POST",
        }),
      );
    } catch (e) {
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="playground-grid">
      <section className="panel composer">
        <div className="section-title">
          <div>
            <p className="eyebrow">ASK YOUR MODEL</p>
            <h2>A local request</h2>
          </div>
          <div className="segmented" aria-label="Input format">
            <button aria-pressed={!editor} onClick={() => setEditor(false)}>
              Guided
            </button>
            <button
              aria-pressed={editor}
              onClick={() => {
                if (!queryError) setRaw(pretty(query));
                setEditor(true);
              }}
            >
              JSON
            </button>
          </div>
        </div>
        <p className="muted">
          Target version <code>{short(model.context.theory_version)}</code>.
          Accepted knowledge runs locally.
        </p>
        <form
          onSubmit={(e) => {
            e.preventDefault();
            void submit();
          }}
        >
          {readError && (
            <Notice>
              Could not refresh this request: {readError}. Any result shown is
              the last retrieved state.
            </Notice>
          )}
          {editor ? (
            <JsonEditor
              label="Structured query JSON"
              value={raw}
              onChange={setRaw}
              rows={17}
            />
          ) : (
            <>
              <label htmlFor="operation">Operation</label>
              <select
                id="operation"
                value={op}
                onChange={(e) => setOp(e.target.value)}
              >
                <option value="capabilities">Inspect capabilities</option>
                <option value="evaluate">Evaluate a function</option>
                <option value="check_claim">Check a Boolean claim</option>
                <option value="find_plan">Find a plan</option>
                <option value="check_certificate">
                  Check an invariant certificate
                </option>
                <option value="explain">Explain a recorded result</option>
              </select>
              {["evaluate", "check_claim", "find_plan"].includes(op) && (
                <>
                  <label htmlFor="symbol">
                    {op === "find_plan" ? "Goal" : "Function"}
                  </label>
                  <select
                    id="symbol"
                    value={symbol}
                    onChange={(e) => choose(e.target.value)}
                    disabled={!choices.length}
                  >
                    {!choices.length && (
                      <option value="">None available</option>
                    )}
                    {choices.map(([s]) => (
                      <option key={s}>{s}</option>
                    ))}
                  </select>
                </>
              )}
              {["evaluate", "check_claim"].includes(op) &&
                validSymbol &&
                Object.entries(decls[symbol].params || {}).map(([k, t]) => (
                  <ValueField
                    key={`${symbol}:${k}`}
                    label={k}
                    spec={t}
                    declarations={decls}
                    value={args[k]}
                    onChange={(v) => setArgs({ ...args, [k]: v })}
                  />
                ))}
              {op === "find_plan" && validSymbol && state !== null && (
                <>
                  <ValueField
                    label="Initial state"
                    spec={decls[symbol].state!}
                    declarations={decls}
                    value={state}
                    onChange={setState}
                  />
                  <label htmlFor="selection">Action selection</label>
                  <select
                    id="selection"
                    value={selection}
                    onChange={(e) =>
                      setSelection(e.target.value as "all" | "explicit")
                    }
                  >
                    <option value="all">All module actions</option>
                    <option value="explicit">Only selected actions</option>
                  </select>
                  {selection === "explicit" && (
                    <fieldset>
                      <legend>Allowed actions</legend>
                      {transitions.map(([s]) => (
                        <label className="check" key={s}>
                          <input
                            type="checkbox"
                            checked={actions.includes(s)}
                            onChange={(e) =>
                              setActions(
                                e.target.checked
                                  ? [...actions, s]
                                  : actions.filter((a) => a !== s),
                              )
                            }
                          />
                          {s}
                        </label>
                      ))}
                      <small>
                        Selecting none means no actions are allowed.
                      </small>
                    </fieldset>
                  )}
                  <label htmlFor="depth">Maximum plan depth (optional)</label>
                  <input
                    id="depth"
                    type="number"
                    min="0"
                    step="1"
                    value={depth}
                    onChange={(e) => setDepth(e.target.value)}
                    placeholder="No depth bound"
                  />
                </>
              )}
              {op === "check_certificate" && (
                <>
                  <p className="muted">
                    Supply an invariant certificate for this exact theory. Proof
                    status is checked locally.
                  </p>
                  <JsonEditor
                    label="Certificate JSON"
                    value={certificate}
                    onChange={setCertificate}
                  />
                  <label htmlFor="backend">Checker</label>
                  <select
                    id="backend"
                    value={backend}
                    onChange={(e) => setBackend(e.target.value)}
                  >
                    <option value="lean">
                      Lean kernel + finite correspondence
                    </option>
                    <option value="finite">
                      Exhaustive finite correspondence
                    </option>
                  </select>
                </>
              )}
              {op === "explain" && (
                <>
                  <label htmlFor="result-id">Result ID from this ADM</label>
                  <input
                    id="result-id"
                    value={explainId}
                    onChange={(e) => setExplainId(e.target.value)}
                    required
                  />
                </>
              )}
            </>
          )}
          <details className="budget">
            <summary>Work limits</summary>
            <div className="two-columns">
              {Object.entries(budget).map(([key, value]) => (
                <div key={key}>
                  <label htmlFor={key}>{key.replaceAll("_", " ")}</label>
                  <input
                    id={key}
                    type="number"
                    min="1"
                    max={limits[key as keyof Limits]}
                    step="1"
                    required
                    value={value || ""}
                    onChange={(e) =>
                      setBudget({ ...budget, [key]: Number(e.target.value) })
                    }
                  />
                </div>
              ))}
            </div>
          </details>
          {queryError && <Notice>{queryError}</Notice>}
          {error && <Notice error>{error}</Notice>}
          <button className="primary wide" disabled={busy || !!queryError}>
            {busy ? "Submitting…" : "Run locally"}{" "}
            <span aria-hidden="true">↗</span>
          </button>
          <p className="footnote">
            Ask uses this ADM only. Use Learning to propose new knowledge. Use
            Ask for natural-language interaction. Local debug runs explicit
            requests without an LLM.
          </p>
          {!queryError && (
            <JsonDetail
              label="Preview the exact structured query"
              value={query}
            />
          )}
        </form>
      </section>
      {record ? (
        <ResultPanel
          request={record}
          busy={busy}
          onCancel={() => void control("cancel")}
          onRetry={() => void control("retry")}
        />
      ) : (
        <section className="panel result-placeholder">
          <span className="result-mark" aria-hidden="true">
            ∴
          </span>
          <h2>Reasoning you can inspect.</h2>
          <p>
            Run a request to see the local result, its exact model version, and
            what was checked.
          </p>
          <div className="mini-flow">
            <span>Accepted model</span>
            <span>→</span>
            <span>Local computation</span>
            <span>→</span>
            <span>Bound result</span>
          </div>
        </section>
      )}
    </div>
  );
}
