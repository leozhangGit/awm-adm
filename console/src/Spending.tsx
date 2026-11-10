import { useEffect, useRef, useState } from "react";
import { api } from "./api.ts";
import { JsonDetail, Notice } from "./components.tsx";
import { dollars, microUsd } from "./chat.ts";

type Settings = {
  generation: number;
  enabled: boolean;
  total_micro_usd: number;
  interaction_micro_usd: number;
  learning_micro_usd: number;
  legacy_hold_micro_usd: number | null;
  legacy_grants: number;
  suspended_lanes: string[];
  usage: { interaction: number; learning: number };
};
type Price = {
  bound_profile: string;
  input_micro_usd_per_million: number;
  output_micro_usd_per_million: number;
  valid_until_ms: number;
  synthetic: boolean;
  input_bound: number;
};
type Options = {
  connection_id: string;
  connection_version: number;
  configuration_digest: string;
  items: Price[];
};
const requestApi = <T,>(path: string, body?: unknown, method = "POST") =>
  api<T>(path, {
    ...(body === undefined ? {} : { method, body }),
  });

export function Spending() {
  const [settings, setSettings] = useState<Settings | null>(null);
  const [values, setValues] = useState(["0", "0", "0", "0"]);
  const [enabled, setEnabled] = useState(false);
  const [resume, setResume] = useState<string[]>([]);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  async function load() {
    const s = await requestApi<Settings>("/spending");
    setSettings(s);
    setEnabled(s.enabled);
    setValues(
      [
        s.total_micro_usd,
        s.interaction_micro_usd,
        s.learning_micro_usd,
        s.legacy_hold_micro_usd || 0,
      ].map((x) => String((x || 0) / 1_000_000)),
    );
    setResume([]);
  }
  useEffect(() => {
    void load().catch((e) => setError(e.message));
  }, []);
  return (
    <section className="panel" aria-label="Installation spending">
      <h2>Installation spending</h2>
      <p>
        Set lifetime ceilings for this installation. Ask and teaching have
        separate portions. Each conversation still needs its own allowance;
        saving these settings makes no provider call.
      </p>
      {error && (
        <Notice error>
          {error} Refresh the settings before retrying a stale change.
        </Notice>
      )}
      {message && <Notice>{message}</Notice>}
      {settings && (
        <>
          <p>
            Allocated or retained: Ask {dollars(settings.usage.interaction)} ·
            Teaching {dollars(settings.usage.learning)}.
          </p>
          <form
            onSubmit={(e) => {
              e.preventDefault();
              setBusy(true);
              setError("");
              setMessage("");
              void (async () => {
                const [total, interaction, learning, hold] =
                  values.map(microUsd);
                await requestApi(
                  "/spending",
                  {
                    expected_generation: settings.generation,
                    enabled,
                    total_micro_usd: total,
                    interaction_micro_usd: interaction,
                    learning_micro_usd: learning,
                    legacy_hold_micro_usd: hold || null,
                    resume_lanes: resume,
                  },
                  "PUT",
                );
                await load();
                setMessage(
                  "Spending ceilings saved. Existing charges and unknown reservations remain accounted for.",
                );
              })()
                .catch((e) => setError(e.message))
                .finally(() => setBusy(false));
            }}
          >
            <div className="learning-grid">
              {[
                "Total installation ceiling (USD)",
                "Ask portion (USD)",
                "Teaching portion (USD)",
                "Historic unpriced-call hold (USD)",
              ].map((label, i) => (
                <label key={label}>
                  {label}
                  <input
                    inputMode="decimal"
                    value={values[i]}
                    required
                    onChange={(e) =>
                      setValues(
                        values.map((x, j) => (j === i ? e.target.value : x)),
                      )
                    }
                  />
                </label>
              ))}
            </div>
            {!!settings.legacy_grants && (
              <p>
                Historic calls have no verified dollar valuation. A positive
                conservative hold is required and cannot be reduced here. It is
                not an invoice.
              </p>
            )}
            <label>
              <input
                type="checkbox"
                checked={enabled}
                onChange={(e) => setEnabled(e.target.checked)}
              />{" "}
              Allow new priced work within these ceilings
            </label>
            {settings.suspended_lanes.map((lane) => (
              <label key={lane}>
                <input
                  type="checkbox"
                  checked={resume.includes(lane)}
                  onChange={(e) =>
                    setResume(
                      e.target.checked
                        ? [...resume, lane]
                        : resume.filter((x) => x !== lane),
                    )
                  }
                />{" "}
                Resume {lane} after reviewing its overrun; retained charges stay
                counted
              </label>
            ))}
            <div className="buttons">
              <button className="primary" disabled={busy}>
                Save spending ceilings
              </button>
              <button
                type="button"
                disabled={busy}
                onClick={() =>
                  void load()
                    .then(() => setError(""))
                    .catch((e) => setError(e.message))
                }
              >
                Refresh settings
              </button>
            </div>
          </form>
          <JsonDetail label="Spending details" value={settings} />
        </>
      )}
    </section>
  );
}

export function ConnectionPricing({ id }: { id: string }) {
  const [options, setOptions] = useState<Options | null>(null);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [busy, setBusy] = useState(false);
  const identity = useRef<{ meaning: string; key: string } | null>(null);
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    if (options) {
      panel.current?.focus();
      panel.current?.scrollIntoView({ block: "nearest" });
    }
  }, [options]);
  return (
    <>
      <button
        disabled={busy}
        onClick={() => {
          setBusy(true);
          setError("");
          setMessage("");
          void requestApi<Options>(`/connections/${id}/price-options`)
            .then(setOptions)
            .catch((e) => setError(e.message))
            .finally(() => setBusy(false));
        }}
      >
        Review pricing
      </button>
      {error && <Notice error>{error}</Notice>}
      {message && <Notice>{message}</Notice>}
      {options && (
        <section
          className="notice"
          ref={panel}
          tabIndex={-1}
          aria-label="Connection pricing review"
        >
          {!options.items.length && (
            <p>
              This exact model has no current audited price and token bound.
              Chat cannot spend through it yet. Keep the configured model or
              choose a supported connection explicitly; no model is changed
              automatically.
            </p>
          )}
          {options.items.map((p) => (
            <div key={p.bound_profile}>
              <strong>
                {p.synthetic
                  ? "Synthetic recorded pricing · no external calls"
                  : "Audited conservative token pricing"}
              </strong>
              <p>
                Per million tokens: input{" "}
                {dollars(p.input_micro_usd_per_million)}, output{" "}
                {dollars(p.output_micro_usd_per_million)}. Each call reserves up
                to {p.input_bound.toLocaleString()} input tokens plus its output
                cap. Valid until {new Date(p.valid_until_ms).toLocaleString()}.
              </p>
              <p>
                Installing replaces this connection's prior price for future
                work and may require fresh conversation allowances. It does not
                authorize a call.
              </p>
              <button
                disabled={busy}
                onClick={() => {
                  setBusy(true);
                  setError("");
                  const body = {
                    connection_id: options.connection_id,
                    connection_version: options.connection_version,
                    configuration_digest: options.configuration_digest,
                    bound_profile: p.bound_profile,
                    input_micro_usd_per_million: p.input_micro_usd_per_million,
                    output_micro_usd_per_million:
                      p.output_micro_usd_per_million,
                    valid_until_ms: p.valid_until_ms,
                  };
                  const meaning = JSON.stringify(body);
                  if (identity.current?.meaning !== meaning)
                    identity.current = { meaning, key: crypto.randomUUID() };
                  void requestApi("/prices", {
                    ...body,
                    idempotency_key: identity.current.key,
                  })
                    .then(() => {
                      setOptions(null);
                      setMessage(
                        "Price installed. Set up an allowance in Ask or Teach to authorize work.",
                      );
                    })
                    .catch((e) => setError(e.message))
                    .finally(() => setBusy(false));
                }}
              >
                Install this price
              </button>
            </div>
          ))}
          <button onClick={() => setOptions(null)}>Close pricing review</button>
        </section>
      )}
    </>
  );
}
