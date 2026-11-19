export type Exchange = {
  id: string;
  idempotency_key: string;
  channel: string;
  origin: string;
  created_at_ms: number;
  status: string;
  text: string;
  reply: string | null;
  outcome_text: string | null;
  explanation: string | null;
  outcome_label?: string | null;
  failure_code: string | null;
};
export type Message = {
  idempotency_key: string;
  text: string;
  attachments: string[];
  reply_to: string | null;
};
export function newMessage(
  channel: "ask" | "teach",
  text: string,
  selected: string[],
  reference: string | null,
): Message {
  return {
    idempotency_key: crypto.randomUUID(),
    text: text.trim(),
    attachments: channel === "teach" ? [...selected] : [],
    reply_to: reference,
  };
}
export const working = (status: string) =>
  [
    "queued",
    "preparing",
    "awaiting_provider",
    "awaiting_local",
    "awaiting_narration",
    "running",
    "learning",
    "extracting",
    "publishing",
  ].includes(status);
export function replyText(item: Exchange): string {
  return (
    item.explanation ||
    item.outcome_text ||
    item.reply ||
    (working(item.status) ? "Working…" : "No reply is available.")
  );
}
export function outcomeNote(item: Exchange): string | null {
  if (
    !item.explanation ||
    !item.outcome_text ||
    item.explanation === item.outcome_text
  )
    return null;
  return item.outcome_label || item.outcome_text;
}
export function nextReference(
  items: Exchange[],
  previous: string | null,
): string | null {
  const item = items.find((i) => i.id === previous);
  return item && !working(item.status) ? item.id : null;
}
export function savedMessage(
  storage: Pick<Storage, "getItem">,
  key: string,
): Message | null {
  try {
    const v = JSON.parse(storage.getItem(key) || "null");
    return v &&
      typeof v.idempotency_key === "string" &&
      typeof v.text === "string" &&
      Array.isArray(v.attachments) &&
      v.attachments.every((a: unknown) => typeof a === "string") &&
      (v.reply_to === null || typeof v.reply_to === "string")
      ? v
      : null;
  } catch {
    return null;
  }
}
