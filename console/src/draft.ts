// Tab-local text only; a draft never carries submission or spending authority.
export function readDraft(
  storage: Pick<Storage, "getItem">,
  key: string,
): string {
  try {
    const text = storage.getItem(key) || "";
    return text.length <= 16384 ? text : "";
  } catch {
    return "";
  }
}
export function saveDraft(
  storage: Pick<Storage, "setItem" | "removeItem">,
  key: string,
  text: string,
) {
  try {
    if (text && text.length <= 16384) storage.setItem(key, text);
    else storage.removeItem(key);
  } catch {
    /* Storage may be disabled; the in-memory draft remains editable. */
  }
}
