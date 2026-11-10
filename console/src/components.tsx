import { useId, useState } from "react";
import type { ReactNode } from "react";
import type { Declaration, Json, RequestView, Spec } from "./types.ts";
import { active, pretty, short } from "./types.ts";
import { initial, resolve } from "./query.ts";

export function Notice({
  children,
  error = false,
}: {
  children: ReactNode;
  error?: boolean;
}) {
  return (
    <div
      className={`notice ${error ? "error" : ""}`}
      role={error ? "alert" : "status"}
    >
      {children}
    </div>
  );
}
export function Badge({
  children,
  tone = "neutral",
}: {
  children: ReactNode;
  tone?: string;
}) {
  return <span className={`badge ${tone}`}>{children}</span>;
}
export function JsonDetail({
  label = "JSON details",
  value,
}: {
  label?: string;
  value: unknown;
}) {
  return (
    <details className="json-detail">
      <summary>{label}</summary>
      <pre>{pretty(value)}</pre>
    </details>
  );
}
export function Field({
  label,
  children,
  hint,
}: {
  label: string;
  children: ReactNode;
  hint?: string;
}) {
  return (
    <div className="field">
      <span className="field-label">{label}</span>
      {children}
      {hint && <small>{hint}</small>}
    </div>
  );
}
export function JsonEditor({
  label,
  value,
  onChange,
  rows = 10,
}: {
  label: string;
  value: string;
  onChange: (v: string) => void;
  rows?: number;
}) {
  const id = useId();
  return (
    <div className="field">
      <label htmlFor={id}>{label}</label>
      <textarea
        id={id}
        className="code"
        spellCheck={false}
        rows={rows}
        value={value}
        onChange={(e) => onChange(e.target.value)}
      />
    </div>
  );
}

export function ValueField({
  label,
  spec,
  declarations,
  value,
  onChange,
  depth = 0,
}: {
  label: string;
  spec: Spec;
  declarations: Record<string, Declaration>;
  value: Json;
  onChange: (v: Json) => void;
  depth?: number;
}) {
  const id = useId();
  let t: Spec;
  try {
    t = resolve(spec, declarations);
    if (depth > 12) throw Error("Use JSON for deeply nested values.");
  } catch (e) {
    return <Notice error>{String(e)}</Notice>;
  }
  if (t.kind === "refined")
    return (
      <div>
        <ValueField
          {...{ label, declarations, value, onChange }}
          spec={t.base!}
          depth={depth + 1}
        />
        <small>
          Additional model conditions are checked locally when you run.
        </small>
      </div>
    );
  if (t.kind === "record")
    return (
      <fieldset>
        <legend>{label}</legend>
        {Object.entries(t.fields!).length === 0 ? (
          <small>Empty record · no fields needed</small>
        ) : (
          Object.entries(t.fields!).map(([k, s]) => (
            <ValueField
              key={k}
              label={`${label}.${k}`}
              spec={s}
              declarations={declarations}
              value={(value as Record<string, Json>)[k]}
              depth={depth + 1}
              onChange={(v) =>
                onChange({ ...(value as Record<string, Json>), [k]: v })
              }
            />
          ))
        )}
      </fieldset>
    );
  if (t.kind === "sum") {
    const v = value as { tag: string; value: Json };
    return (
      <fieldset>
        <legend>{label}</legend>
        <label htmlFor={id}>{label} variant</label>
        <select
          id={id}
          value={v.tag}
          onChange={(e) =>
            onChange({
              tag: e.target.value,
              value: initial(t.variants![e.target.value], declarations),
            })
          }
        >
          {Object.keys(t.variants!).map((tag) => (
            <option key={tag}>{tag}</option>
          ))}
        </select>
        <ValueField
          label={`${label}.${v.tag}`}
          spec={t.variants![v.tag]}
          declarations={declarations}
          value={v.value}
          depth={depth + 1}
          onChange={(child) => onChange({ ...v, value: child })}
        />
      </fieldset>
    );
  }
  if (t.kind === "vector" && t.length! <= 64)
    return (
      <fieldset>
        <legend>{label}</legend>
        {(value as Json[]).map((v, i) => (
          <ValueField
            key={i}
            label={`${label}[${i}]`}
            spec={t.element!}
            declarations={declarations}
            value={v}
            depth={depth + 1}
            onChange={(child) =>
              onChange(
                (value as Json[]).map((old, j) => (j === i ? child : old)),
              )
            }
          />
        ))}
      </fieldset>
    );
  if (t.kind === "bool")
    return (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <select
          id={id}
          value={String(value)}
          onChange={(e) => onChange(e.target.value === "true")}
        >
          <option value="false">False</option>
          <option value="true">True</option>
        </select>
      </div>
    );
  if (t.kind === "enum")
    return (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <select
          id={id}
          value={value as string}
          onChange={(e) => onChange(e.target.value)}
        >
          {t.values!.map((v) => (
            <option key={v}>{v}</option>
          ))}
        </select>
      </div>
    );
  if (t.kind === "int")
    return (
      <div className="field">
        <label htmlFor={id}>{label}</label>
        <input
          id={id}
          type="number"
          required
          min={t.min}
          max={t.max}
          step="1"
          value={value === null ? "" : String(value)}
          onChange={(e) =>
            onChange(e.target.value === "" ? null : Number(e.target.value))
          }
        />
        <small>
          {t.min} to {t.max}, inclusive
        </small>
      </div>
    );
  return <Notice error>This type requires the JSON editor.</Notice>;
}

const labels: Record<string, string> = {
  received: "Queued for local compute",
  evaluating: "Computing locally",
  succeeded: "Completed locally",
  needs_input: "Needs input",
  waiting_for_learning: "Waiting for learning",
  inconclusive: "Inconclusive",
  cancelled: "Cancelled",
  failed: "Could not complete",
};
export function Status({ status }: { status: string }) {
  return (
    <Badge
      tone={
        status === "succeeded"
          ? "green"
          : active(status)
            ? "blue"
            : status === "failed"
              ? "red"
              : "amber"
      }
    >
      {labels[status] || status}
    </Badge>
  );
}
export function ResultPanel({
  request,
  busy,
  onCancel,
  onRetry,
}: {
  request: RequestView;
  busy: boolean;
  onCancel: () => void;
  onRetry: () => void;
}) {
  const result = request.result;
  const value = result?.value;
  const historical =
    request.pinned_context.policy_epoch !==
      request.current_context.policy_epoch ||
    request.pinned_context.theory_root !== request.current_context.theory_root;
  const actions = Array.isArray(value?.plan) ? value.plan : [];
  return (
    <section className="panel result-panel" aria-label="Request result">
      <div className="section-title">
        <div>
          <p className="eyebrow">LOCAL RESULT</p>
          <h2>{labels[request.status] || request.status}</h2>
        </div>
        <Status status={request.status} />
      </div>
      <p className="muted">
        Request <code>{short(request.request_id)}</code> · Version{" "}
        <code>{short(request.pinned_context.theory_root)}</code> · Epoch{" "}
        {request.pinned_context.policy_epoch}
      </p>
      {historical && (
        <Notice>
          This result belongs to an earlier model or owner policy. Its original
          meaning is preserved. Run a new request to use the current context.
        </Notice>
      )}
      {active(request.status) && (
        <>
          <p>
            Accepted by the local service. You can leave this page; the request
            will remain available in History.
          </p>
          <button className="secondary" disabled={busy} onClick={onCancel}>
            Cancel request
          </button>
        </>
      )}
      {request.error && (
        <Notice error>
          {request.error.message} <code>{request.error.code}</code>
        </Notice>
      )}
      {request.status === "needs_input" && (
        <p>
          The accepted model could not support this request. Review the input or
          model. Start a bounded learning episode to acquire the missing
          knowledge.
          <br />
          <a
            href={`#view=learning&adm=${request.adm_id}&request=${request.request_id}`}
          >
            Learn for this request →
          </a>
        </p>
      )}
      {request.status === "inconclusive" && (
        <p>
          The local check stopped without a conclusion. This does not establish
          a knowledge gap or an unreachable goal.
        </p>
      )}
      {["inconclusive", "failed", "needs_input"].includes(request.status) && (
        <button
          className="secondary"
          disabled={busy || historical}
          onClick={onRetry}
        >
          Retry original request
        </button>
      )}
      {result && (
        <>
          {value?.outcome === "found" && (
            <div className="answer">
              <strong>{String(value.steps)} steps</strong>
              <span>Shortest action count under the selected actions</span>
            </div>
          )}
          {value?.outcome && value.outcome !== "found" && (
            <div className="answer">
              <strong>
                {value.outcome === "unreachable"
                  ? "Goal unreachable"
                  : value.outcome === "no_plan_within_depth"
                    ? "No plan within the depth bound"
                    : String(value.outcome)}
              </strong>
              <span>For this exact model, state and action selection</span>
            </div>
          )}
          {Object.hasOwn(value!, "value") && (
            <div className="answer">
              <pre>{pretty(value!.value)}</pre>
              <span>Computed from accepted local definitions</span>
            </div>
          )}
          {actions.length > 0 && (
            <ol className="plan-steps">
              {actions.map((action, i) => {
                const step = action as {
                  transition: string;
                  parameters: Record<string, Json>;
                  cost: number;
                };
                return (
                  <li key={i}>
                    <strong>{step.transition}</strong>
                    {Object.keys(step.parameters || {}).length > 0 && (
                      <span>
                        {" "}
                        · parameters {JSON.stringify(step.parameters)}
                      </span>
                    )}
                    <small> · cost {step.cost}</small>
                  </li>
                );
              })}
            </ol>
          )}
          {value?.certificate_status && (
            <div className="answer">
              <strong>Invariant {String(value.certificate_status)}</strong>
              <span>
                Lean kernel: {result.lean_kernel} · Executable correspondence:{" "}
                {result.exhaustive_finite}
              </span>
            </div>
          )}
          {value?.explanation && (
            <JsonDetail
              label="Recorded result explanation"
              value={value.explanation}
            />
          )}
          <div className="chips">
            {result.claims.map((c) => (
              <Badge key={c} tone="green">
                {c.replaceAll("_", " ")}
              </Badge>
            ))}
          </div>
          <JsonDetail
            label="Exact bindings, proof checks and local trace"
            value={result}
          />
        </>
      )}
      <JsonDetail
        label="Submitted query and attempt history"
        value={{
          query: request.query,
          attempts: request.attempts,
          pinned_context: request.pinned_context,
          current_context: request.current_context,
        }}
      />
    </section>
  );
}

export function CopyButton({ value }: { value: string }) {
  const [copied, setCopied] = useState(false);
  return (
    <button
      className="text-button"
      onClick={async () => {
        try {
          await navigator.clipboard.writeText(value);
          setCopied(true);
        } catch {
          setCopied(false);
        }
      }}
    >
      {copied ? "Copied" : "Copy ID"}
    </button>
  );
}
