import { useState } from "react";
import { api } from "./api";
type Context = Record<string, string | number>;

export type TeachingTaskRecord = {
  id: string;
  status: string;
  objective: string | null;
  summary?: string;
  specification_digest?: string;
  source_queue?: boolean;
  budget?: { expires_at_ms: number };
  source_review?: {
    sources: string[];
    entities: string[];
    predicates: string[];
    coverage: string[];
  }[];
  execution?: {
    version: number;
    status: string;
    phase: string;
    steps: {
      id: string;
      status: string;
      source_progress?: {
        received: number;
        accepted: number;
        attention: number;
        pending: number;
        attention_items?: { label: string; reason: string }[];
      };
      feed_id?: string;
    }[];
    review?: {
      digest: string;
      expires_at_ms: number;
      behaviors: { symbol: string; behavior: string }[];
    } | null;
    narration?: { explanation: string };
    narration_failure?: string;
    summary?: {
      stop_reason?: string;
      vocabulary?: string;
      accepted: string[];
      unresolved: { objective: string; reason: string }[];
      followup?: { text?: string } | null;
      spend: {
        settled_micro_usd: number;
        reserved_micro_usd: number;
        unresolved_calls: number;
      };
    } | null;
  };
};

export function TeachingTask({
  task,
  context,
  disabled,
  act,
  renew,
}: {
  task: TeachingTaskRecord;
  context: Context;
  disabled: boolean;
  act: (id: string, body: Record<string, unknown>) => void;
  renew: (id: string, body: Record<string, unknown>) => void;
}) {
  const [starting, setStarting] = useState(true);
  const [sourceConsent, setSourceConsent] = useState(false);
  const [appendAccess, setAppendAccess] = useState<{
    token: string;
    id: string;
    endpoint: string;
    expires_in: number;
  } | null>(null);
  const [accessError, setAccessError] = useState("");
  const [renewal, setRenewal] = useState<{
    command: Record<string, unknown> & { expires_at_ms: number };
    cap_micro_usd: number;
    remaining_micro_usd: number;
    max_calls: number;
    calls_used: number;
  } | null>(null);
  const [renewalError, setRenewalError] = useState("");
  const run = task.execution;
  const active = ["queued", "running", "awaiting_decision", "paused"].includes(
    task.status,
  );
  const command = (action: string) =>
    act(task.id, {
      idempotency_key: crypto.randomUUID(),
      specification_digest: task.specification_digest,
      context,
      expected_version: run?.version || 0,
      action,
      review_digest: run?.review?.digest || null,
      source_consent: sourceConsent,
    });
  return (
    <section className="panel" aria-label="Teaching task status">
      <strong>
        {run ? "Teaching" : "Preparation"} · {task.status.replaceAll("_", " ")}
      </strong>
      <p>
        {task.summary ||
          task.objective ||
          "Waiting for your teaching intention."}
      </p>
      {!run && ["awaiting_review", "prepared"].includes(task.status) && (
        <div aria-label="Teaching review time">
          <button
            className="secondary"
            disabled={disabled}
            onClick={async () => {
              setRenewalError("");
              try {
                setRenewal(
                  await api(
                    `/adms/${context.adm_id}/tasks/${task.id}/renewal`,
                    {},
                  ),
                );
              } catch (e) {
                setRenewalError((e as Error).message);
              }
            }}
          >
            Review more time…
          </button>
          {renewalError && <p role="alert">{renewalError}</p>}
          {renewal && (
            <div className="chat-decision">
              <p>
                Keep this preparation and extend review and execution authority
                until {new Date(renewal.command.expires_at_ms).toLocaleString()}
                .
              </p>
              <p>
                The original ${(renewal.cap_micro_usd / 1000000).toFixed(2)} cap
                stays unchanged; $
                {(renewal.remaining_micro_usd / 1000000).toFixed(4)} remains,
                with {renewal.calls_used} of {renewal.max_calls} calls used. All
                token and work caps stay unchanged. This starts no work and
                repeats no provider call.
              </p>
              <button
                disabled={disabled}
                onClick={() => {
                  renew(task.id, renewal.command);
                  setRenewal(null);
                }}
              >
                Confirm more time, same limits
              </button>
              <button
                className="secondary"
                disabled={disabled}
                onClick={() => setRenewal(null)}
              >
                Not now
              </button>
            </div>
          )}
        </div>
      )}
      {task.status === "prepared" && !starting && (
        <button disabled={disabled} onClick={() => setStarting(true)}>
          Start teaching…
        </button>
      )}
      {task.status === "prepared" && starting && (
        <div className="chat-decision" aria-label="Confirm teaching execution">
          <p>
            Use the saved specification and the remaining teaching allowance to
            develop this capability. The provider receives the prepared inputs,
            interfaces, accepted model definitions and bounded diagnostic
            feedback. Completion explanation may include the checked outcome and
            linked local answer.
          </p>
          <p>
            Checked candidates are admitted automatically when independent owner
            requirements exist. Otherwise you will review the candidate before
            admission. Proposed behavioral requirements remain uninstalled. For
            supplied material, review its claims before admission. Source
            permissions and finite coverage below need your explicit consent.
          </p>
          <p>
            No additional allowance is created. Pausing or cancelling keeps
            accepted work and charges for calls already dispatched.
          </p>
          {!!task.source_review?.length && (
            <>
              {task.source_review.map((r, i) => (
                <div key={i}>
                  <p>
                    <strong>Sources:</strong> {r.sources.join(", ")}.{" "}
                    <strong>Entities:</strong> {r.entities.join(", ")}.
                  </p>
                  <p>{r.predicates.join("; ")}</p>
                  <p>Coverage: {r.coverage.join("; ")}</p>
                </div>
              ))}
              <label>
                <input
                  type="checkbox"
                  checked={sourceConsent}
                  onChange={(e) => setSourceConsent(e.target.checked)}
                />{" "}
                Authorize this source coverage and sharing the supplied material
                with this task’s provider for extraction. Corrections hold the
                replaced source’s support until replacement is admitted.
              </label>
              {task.source_queue && (
                <p>
                  This also permits future pushed material from these sources
                  within the same cap and expiry. Every candidate still needs
                  review. No connector is installed.
                </p>
              )}
            </>
          )}
          <button
            disabled={
              disabled ||
              (task.budget?.expires_at_ms || 0) <= Date.now() ||
              (!!task.source_review?.length && !sourceConsent)
            }
            onClick={() => command("start")}
          >
            Start within remaining allowance
          </button>
          <button
            className="secondary"
            disabled={disabled}
            onClick={() => setStarting(false)}
          >
            Not now
          </button>
        </div>
      )}
      {run?.steps.map(
        (step) =>
          !!step.source_progress?.attention_items?.length && (
            <section key={step.id} aria-label="Material needing attention">
              <strong>Material needing attention</strong>
              <ul>
                {step.source_progress.attention_items.map((item, i) => (
                  <li key={i}>
                    {item.label}: {item.reason}.
                  </li>
                ))}
              </ul>
              <p>
                The original material is retained. Details contains the
                processing record; another attempt needs a new bounded teaching
                task.
              </p>
            </section>
          ),
      )}
      {run && active && (
        <>
          <p>
            {run.steps.filter((s) => s.status === "accepted").length} of{" "}
            {run.steps.length} parts accepted.
          </p>
          {run.steps.map(
            (step) =>
              step.source_progress && (
                <p key={step.id}>
                  Material: {step.source_progress.received} processing items ·{" "}
                  {step.source_progress.accepted} accepted ·{" "}
                  {step.source_progress.pending} pending ·{" "}
                  {step.source_progress.attention} need attention.
                </p>
              ),
          )}
          {task.source_queue && (
            <div className="actions">
              <button
                className="secondary"
                disabled={disabled || task.status === "paused"}
                onClick={() => command("finish")}
              >
                Finish receiving material
              </button>
              <button
                className="secondary"
                disabled={
                  disabled ||
                  task.status === "paused" ||
                  !run.steps.some((s) => s.feed_id)
                }
                onClick={async () => {
                  try {
                    setAccessError("");
                    setAppendAccess(
                      await api(
                        `/adms/${context.adm_id}/intake/${task.id}/credentials`,
                        {
                          method: "POST",
                          body: {
                            context,
                            specification_digest: task.specification_digest,
                            expected_version: run.version,
                            expires_in: 3600,
                          },
                        },
                      ),
                    );
                  } catch (e) {
                    setAccessError((e as Error).message);
                  }
                }}
              >
                Create append access…
              </button>
            </div>
          )}
          {accessError && <p role="alert">{accessError}</p>}
          {appendAccess && (
            <div className="chat-decision">
              <strong>Private append credential</strong>
              <p>
                Copy once for your local producer. It expires within{" "}
                {appendAccess.expires_in} seconds and can only append to this
                queue or inspect its own receipts.
              </p>
              <textarea
                readOnly
                aria-label="Append credential"
                value={appendAccess.token}
              />
              <p>Endpoint: {appendAccess.endpoint}</p>
              <button
                className="secondary"
                onClick={async () => {
                  await api(`/auth/tokens/${appendAccess.id}`, {
                    method: "DELETE",
                  });
                  setAppendAccess(null);
                }}
              >
                Revoke access
              </button>
              <button
                className="secondary"
                onClick={() => setAppendAccess(null)}
              >
                Hide credential
              </button>
            </div>
          )}
          {task.status === "awaiting_decision" && (
            <div
              className="chat-decision"
              aria-label="Review learning candidate"
            >
              <p>
                Review the proposed behavior and evidence below. Exact
                definitions and provenance are available in Details. Approval
                still requires local admission checks.
              </p>
              <ul>
                {run.review?.behaviors.map((b, i) => (
                  <li key={`${b.symbol}-${i}`}>
                    <strong>{b.symbol.split(".").at(-1)}</strong>: {b.behavior}
                  </li>
                ))}
              </ul>
              <button
                disabled={
                  disabled ||
                  !run.review ||
                  run.review.expires_at_ms <= Date.now()
                }
                onClick={() => command("approve")}
              >
                Approve candidate meaning
              </button>
              <button
                className="secondary"
                disabled={disabled}
                onClick={() => command("decline")}
              >
                Decline candidate
              </button>
            </div>
          )}
          <div className="actions">
            <button
              className="secondary"
              disabled={disabled}
              onClick={() =>
                command(task.status === "paused" ? "resume" : "pause")
              }
            >
              {task.status === "paused" ? "Resume teaching" : "Pause teaching"}
            </button>
            <button
              className="secondary"
              disabled={disabled}
              onClick={() => command("cancel")}
            >
              Cancel remaining work
            </button>
          </div>
        </>
      )}
      {run?.summary && (
        <div aria-label="Teaching outcome">
          {run.summary.stop_reason && (
            <p>
              Stopped: {run.summary.stop_reason.replaceAll("_", " ")}. Accepted
              work is preserved; continuation requires a new task.
            </p>
          )}
          {!!run.summary.accepted.length && (
            <p>
              <strong>Accepted:</strong> {run.summary.accepted.join("; ")}.
            </p>
          )}
          {!!run.summary.unresolved.length && (
            <p>
              <strong>Unresolved:</strong>{" "}
              {run.summary.unresolved
                .map((s) => `${s.objective} (${s.reason.replaceAll("_", " ")})`)
                .join("; ")}
              .
            </p>
          )}
          {run.summary.followup?.text && <p>{run.summary.followup.text}</p>}
          {run.summary.vocabulary && run.summary.vocabulary !== "installed" && (
            <p className="muted">
              The suggested interaction vocabulary was not installed. Accepted
              model knowledge remains available.
            </p>
          )}
          <p>
            Settled usage: $
            {(run.summary.spend.settled_micro_usd / 1000000).toFixed(4)}.
            Retained reservation: $
            {(run.summary.spend.reserved_micro_usd / 1000000).toFixed(4)}
            {run.summary.spend.unresolved_calls
              ? "; includes unverified usage"
              : ""}
            .
          </p>
          {run.narration && (
            <p>
              <strong>Provider explanation:</strong> {run.narration.explanation}
            </p>
          )}
          {run.narration_failure && (
            <p className="muted">
              The explanation was unavailable. The checked outcome above remains
              available.
            </p>
          )}
        </div>
      )}
      <p className="muted">
        Exact scope, candidate definitions, receipt order and accounting are
        available in Details.
      </p>
    </section>
  );
}
