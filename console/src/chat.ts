// Small rendering grammar: text, emphasis and code only. No HTML, links or embeds.
export function recoveryAdvice(code?: string): string {
  if (code === "stale_context")
    return "The model or approval changed. Review the current state; an unchanged retry cannot renew this approval.";
  if (code === "forbidden" || code === "unauthorized")
    return "Check your login and owner permissions before trying again. Retrying does not grant access.";
  if (code === "quota_exceeded" || code === "resource_exhausted")
    return "Review the remaining allowance or storage capacity. Retrying does not increase a limit or refund uncertain usage.";
  if (code === "invalid_input" || code === "unsupported")
    return "Review the input and supported scope before submitting a corrected request.";
  return "Review saved history and Details before recovering this submission; no automatic retry is made.";
}

export function inlineParts(
  text: string,
): { kind: "text" | "strong" | "code"; text: string }[] {
  return text
    .split(/(\*\*[^*\n]+\*\*|`[^`\n]+`)/g)
    .filter(Boolean)
    .map((part) =>
      part.startsWith("**") && part.endsWith("**")
        ? { kind: "strong", text: part.slice(2, -2) }
        : part.startsWith("`") && part.endsWith("`")
          ? { kind: "code", text: part.slice(1, -1) }
          : { kind: "text", text: part },
    );
}
export function workLabel(work?: {
  status: string;
  dispatch_status?: string;
  flow?: string;
}): string {
  if (!work) return "Ready";
  if (work.status === "queued") return "Queued";
  if (work.status === "awaiting_provider")
    return ["leased", "dispatched"].includes(work.dispatch_status || "")
      ? work.flow === "ask"
        ? "Interpreting your question"
        : work.flow === "teach"
          ? "Preparing your teaching task"
          : "Working on clarification"
      : "Queued for a provider worker";
  if (work.status === "awaiting_local") return "Local request submitted";
  if (work.status === "awaiting_narration")
    return ["leased", "dispatched"].includes(work.dispatch_status || "")
      ? "Explaining the saved outcome"
      : "Outcome saved · explanation queued";
  return (
    (
      {
        needs_input: "Waiting for your reply",
        awaiting_review: "Teaching specification ready for review",
        prepared: "Teaching task prepared",
        completed: "Outcome ready",
        needs_learning: "Model knowledge needed",
        unsupported: "Outside supported operations",
        unavailable: "Finished · capability not available yet",
        failed: "Could not complete",
        interrupted: "Interrupted · no automatic retry",
      } as Record<string, string>
    )[work.status] || work.status
  );
}
export function dollars(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 6,
  }).format(value / 1_000_000);
}

export function sameContext(
  a: Record<string, string | number>,
  b?: Record<string, string | number>,
): boolean {
  return (
    !!b &&
    Object.keys(a).length === Object.keys(b).length &&
    Object.keys(a).every((k) => a[k] === b[k])
  );
}

export function microUsd(text: string): number {
  if (!/^\d+(\.\d{1,6})?$/.test(text))
    throw Error(
      "Enter an exact nonnegative USD amount, up to six decimal places.",
    );
  const [whole, fraction = ""] = text.split(".");
  const result = Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
  if (!Number.isSafeInteger(result) || result > 1_000_000_000)
    throw Error("The maximum installation amount is $1,000.");
  return result;
}
