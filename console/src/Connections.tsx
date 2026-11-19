import { useEffect, useRef, useState } from "react";
import { ApiError, api } from "./api.ts";
import { Badge, Notice } from "./components.tsx";
import { sealCredential } from "./credential.ts";

type Connection = {
  state: string;
  generation: number;
  provider: string | null;
  model: string | null;
  has_saved_key: boolean;
  error: string | null;
  operation_id: string | null;
  gateway_key: { key_id: string; spki: string } | null;
  migration_choices: { id: string; provider: string; model: string }[];
};
type Usage = {
  days: {
    date: string;
    input_tokens: number;
    output_tokens: number;
    missing_usage: number;
  }[];
  hours: {
    start: string;
    succeeded: number;
    failed: number;
    unknown: number;
    active: number;
  }[];
};
type Bar = { label: string; a: number; b: number };
function Chart({
  rows,
  first,
  second,
  color,
}: {
  rows: Bar[];
  first: string;
  second: string;
  color: string;
}) {
  const max = Math.max(1, ...rows.flatMap((r) => [r.a, r.b]));
  const width = 720;
  const step = width / Math.max(1, rows.length);
  return (
    <>
      <div className="chart-legend">
        <span style={{ color: "#245746" }}>● {first}</span>
        <span style={{ color }}>● {second}</span>
      </div>
      <svg
        className="usage-chart"
        viewBox="0 0 760 225"
        role="img"
        aria-label={`${first} and ${second} by time`}
      >
        <text x="0" y="14" fontSize="12">
          {max.toLocaleString()}
        </text>
        <line x1="30" y1="190" x2="750" y2="190" stroke="#a8b5ac" />
        {rows.map((r, i) => (
          <g key={i}>
            <title>
              {r.label}: {first} {r.a.toLocaleString()}, {second}{" "}
              {r.b.toLocaleString()}
            </title>
            <rect
              x={30 + i * step + step * 0.1}
              y={190 - (r.a / max) * 160}
              width={step * 0.32}
              height={(r.a / max) * 160}
              fill="#245746"
            />
            <rect
              x={30 + i * step + step * 0.46}
              y={190 - (r.b / max) * 160}
              width={step * 0.32}
              height={(r.b / max) * 160}
              fill={color}
            />
            {(rows.length < 10 || i % 4 === 0) && (
              <text
                x={30 + i * step + step * 0.45}
                y="211"
                textAnchor="middle"
                fontSize="11"
              >
                {r.label}
              </text>
            )}
          </g>
        ))}
      </svg>
      <div className="sr-only">
        <table>
          <caption>
            {first} and {second}
          </caption>
          <thead>
            <tr>
              <th>Time</th>
              <th>{first}</th>
              <th>{second}</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((r, i) => (
              <tr key={i}>
                <th>{r.label}</th>
                <td>{r.a}</td>
                <td>{r.b}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </>
  );
}
export function Connections() {
  const [state, setState] = useState<Connection | null>(null);
  const [usage, setUsage] = useState<Usage | null>(null);
  const [provider, setProvider] = useState("openai");
  const [model, setModel] = useState("");
  const [credential, setCredential] = useState("");
  const [retained, setRetained] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const initialized = useRef(false);
  const pending = useRef<Record<string, unknown> | null>(null);
  async function refresh(signal?: AbortSignal) {
    const [next, counts] = await Promise.all([
      api<Connection>("/connection", { signal }),
      api<Usage>(
        `/connection/usage?timezone=${encodeURIComponent(Intl.DateTimeFormat().resolvedOptions().timeZone)}`,
        { signal },
      ),
    ]);
    setState(next);
    setUsage(counts);
    if (!initialized.current || next.state !== "disabled") {
      setProvider(next.provider || "openai");
      setModel(next.model || "");
      initialized.current = true;
    }
  }
  useEffect(() => {
    const abort = new AbortController();
    let timer: ReturnType<typeof setTimeout>;
    const tick = async () => {
      try {
        await refresh(abort.signal);
      } catch (e) {
        if (!abort.signal.aborted) setError((e as Error).message);
      } finally {
        if (!abort.signal.aborted) timer = setTimeout(tick, 3000);
      }
    };
    void tick();
    return () => {
      abort.abort();
      clearTimeout(timer);
    };
  }, []);
  async function toggle() {
    if (!state || busy) return;
    setBusy(true);
    setError("");
    try {
      if (state.state !== "disabled") {
        await api("/connection/disable", {
          method: "POST",
          body: { idempotency_key: crypto.randomUUID() },
        });
        pending.current = null;
      } else {
        if (!pending.current) {
          const id = crypto.randomUUID();
          const sealed = credential
            ? await sealCredential(state.gateway_key, credential, provider, id)
            : {};
          pending.current = {
            idempotency_key: id,
            provider,
            model,
            expected_generation: state.generation,
            ...sealed,
            ...(retained ? { retained_connection_id: retained } : {}),
          };
        }
        setCredential("");
        await api("/connection/enable", {
          method: "POST",
          body: pending.current,
        });
        pending.current = null;
      }
      await refresh();
    } catch (e) {
      if (e instanceof ApiError && e.status < 500) pending.current = null;
      setError((e as Error).message);
    } finally {
      setBusy(false);
    }
  }
  const locked = busy || state?.state !== "disabled";
  const change = () => {
    pending.current = null;
    setError("");
  };
  return (
    <>
      <section className="panel connection-panel">
        <div className="section-title">
          <div>
            <p className="eyebrow">REMOTE CONNECTION</p>
            <h1>Connection</h1>
          </div>
          {state && (
            <Badge tone={state.state === "enabled" ? "green" : "neutral"}>
              {state.state === "testing"
                ? "Testing…"
                : state.state === "enabled"
                  ? "Enabled"
                  : "Disabled"}
            </Badge>
          )}
        </div>
        <p>
          One connection powers Ask, Teach and explanations. Enable tests the
          connection before making it available.
        </p>
        {error && <Notice error>{error}</Notice>}
        {state?.error && <Notice error>{state.error}</Notice>}
        {Boolean(state?.migration_choices.length) && (
          <label>
            Choose the saved connection to use
            <select
              value={retained}
              disabled={locked}
              onChange={(e) => {
                change();
                setRetained(e.target.value);
                const value = state?.migration_choices.find(
                  (c) => c.id === e.target.value,
                );
                if (value) {
                  setProvider(value.provider);
                  setModel(value.model);
                }
              }}
            >
              <option value="">Choose a saved connection</option>
              {state?.migration_choices.map((c) => (
                <option key={c.id} value={c.id}>
                  {c.provider} · {c.model}
                </option>
              ))}
            </select>
          </label>
        )}
        <div className="two-columns">
          <label>
            Provider
            <select
              value={provider}
              disabled={locked}
              onChange={(e) => {
                change();
                setProvider(e.target.value);
                setCredential("");
              }}
            >
              <option value="openai">OpenAI</option>
              <option value="anthropic">Anthropic</option>
            </select>
          </label>
          <label>
            Model identifier
            <input
              value={model}
              disabled={locked}
              onChange={(e) => {
                change();
                setModel(e.target.value);
              }}
              placeholder="Enter the provider’s model identifier"
              autoComplete="off"
            />
          </label>
        </div>
        <label>
          API key
          <input
            type="password"
            value={credential}
            disabled={locked}
            onChange={(e) => {
              change();
              setCredential(e.target.value);
            }}
            placeholder={
              state?.has_saved_key || retained
                ? "•••••••• · saved key; leave unchanged to reuse"
                : "Enter API key"
            }
            autoComplete="new-password"
            spellCheck={false}
          />
        </label>
        <div className="actions">
          <button
            className="primary"
            disabled={
              !state ||
              busy ||
              (state.state === "disabled" &&
                (!model.trim() ||
                  (!credential &&
                    !pending.current &&
                    !retained &&
                    (!state.has_saved_key || provider !== state.provider))))
            }
            onClick={() => void toggle()}
          >
            {busy
              ? "Saving…"
              : state?.state === "testing"
                ? "Disable"
                : state?.state === "enabled"
                  ? "Disable"
                  : "Enable"}
          </button>
          <small>
            {state?.state === "testing"
              ? "The connection test is running. You can disable it at any time."
              : state?.state === "enabled"
                ? "Disable to change the provider, model or key."
                : "Your saved key is retained when disabled."}
          </small>
        </div>
      </section>
      {usage && (
        <div className="usage-panels">
          <section className="panel">
            <h2>Tokens · past 7 days</h2>
            <Chart
              rows={usage.days.map((d) => ({
                label: d.date.slice(5),
                a: d.input_tokens,
                b: d.output_tokens,
              }))}
              first="Input"
              second="Output"
              color="#638cc1"
            />
            <p className="footnote">
              Provider-reported tokens, including known usage from failed calls.{" "}
              {usage.days.reduce((n, d) => n + d.missing_usage, 0)} calls have
              unverified usage.
            </p>
          </section>
          <section className="panel">
            <h2>Calls · past 24 hours</h2>
            <Chart
              rows={usage.hours.map((h) => ({
                label: new Date(h.start).toLocaleTimeString([], {
                  hour: "2-digit",
                  minute: "2-digit",
                }),
                a: h.succeeded,
                b: h.failed,
              }))}
              first="Succeeded"
              second="Failed"
              color="#bc655d"
            />
            <p className="footnote">
              {usage.hours.reduce((n, h) => n + h.active, 0)} active ·{" "}
              {usage.hours.reduce((n, h) => n + h.unknown, 0)} outcomes unknown.
              Times use your timezone.
            </p>
          </section>
        </div>
      )}
    </>
  );
}
