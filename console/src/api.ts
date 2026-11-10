import type { Json, Session } from "./types.ts";
import { eventFrames, parseJson } from "./query.ts";

const SESSION = "awm-adm-session-csrf";
export class ApiError extends Error {
  code: string;
  status: number;
  constructor(status: number, code: string, message: string) {
    super(message);
    this.code = code;
    this.status = status;
  }
}
let currentSession: Session | null = null;
// Remove obsolete session metadata on upgrade; credentials and CSRF state stay out of persistent storage.
try {
  globalThis.localStorage?.removeItem(SESSION);
} catch {
  /* Storage may be disabled. */
}
export function session(): Session | null {
  return currentSession;
}
export function saveSession(value: Session | null) {
  currentSession = value;
}
export async function api<T>(
  path: string,
  options: {
    method?: string;
    body?: unknown;
    signal?: AbortSignal;
    revision?: string;
  } = {},
): Promise<T> {
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
  };
  const csrf = session()?.csrf;
  if (csrf) headers["X-CSRF-Token"] = csrf;
  if (options.revision) headers["If-Match"] = options.revision;
  const body =
    options.body === undefined ? undefined : JSON.stringify(options.body);
  if (body && new TextEncoder().encode(body).length > 2_097_152)
    throw new Error(
      "The complete request exceeds 2 MiB. Use a smaller snapshot or input.",
    );
  const response = await fetch("/api/v1" + path, {
    method: options.method || "GET",
    headers,
    body,
    credentials: "same-origin",
    signal: options.signal || AbortSignal.timeout(30_000),
  });
  const value = parseJson(await response.text()) as Record<string, unknown>;
  if (!response.ok) {
    if (
      response.status === 401 &&
      ![
        "/auth/login",
        "/auth/setup",
        "/auth/recover",
        "/auth/password",
      ].includes(path)
    )
      window.dispatchEvent(new Event("adm-session-expired"));
    throw new ApiError(
      response.status,
      String(value.code || "request_failed"),
      String(value.message || "The local API could not complete this request."),
    );
  }
  return value as T;
}
export function authApi<T>(path: string, body?: unknown) {
  return api<T>("/auth" + path, {
    method: body === undefined ? "GET" : "POST",
    body,
  });
}
export function download(name: string, value: unknown) {
  const url = URL.createObjectURL(
    new Blob([JSON.stringify(value, null, 2)], { type: "application/json" }),
  );
  const a = document.createElement("a");
  a.href = url;
  a.download = name;
  a.click();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}
export async function readJsonFile(file: File): Promise<Json> {
  if (file.size > 2_000_000)
    throw new Error("Choose a JSON snapshot under 2 MB.");
  return parseJson(await file.text());
}

// Each browser tab owns its cursor. No shared acknowledgment consumes another viewer's events.
export async function watch(
  adm: string,
  signal: AbortSignal,
  changed: () => void,
  status: (text: string) => void,
) {
  const key = `adm-events:${session()?.id}:${adm}`;
  let after = Number(sessionStorage.getItem(key) || "0"),
    failures = 0;
  if (!Number.isSafeInteger(after) || after < 0) after = 0;
  const pause = () =>
    new Promise<void>((resolve) => {
      if (signal.aborted) {
        resolve();
        return;
      }
      const done = () => {
        clearTimeout(timer);
        signal.removeEventListener("abort", done);
        resolve();
      };
      const timer = setTimeout(done, Math.min(5000, 800 * (failures + 1)));
      signal.addEventListener("abort", done, { once: true });
    });
  while (!signal.aborted) {
    try {
      const response = await fetch(
        `/api/v1/adms/${adm}/events?after=${after}&limit=100`,
        {
          headers: { Accept: "text/event-stream" },
          credentials: "same-origin",
          signal,
        },
      );
      if (!response.ok) {
        const v = await response.json();
        throw new ApiError(response.status, v.code, v.message);
      }
      status("Live updates");
      failures = 0;
      const reader = response.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = "";
      try {
        while (!signal.aborted) {
          const { value, done } = await reader.read();
          if (done) break;
          buffer += decoder.decode(value, { stream: true });
          if (buffer.length > 2_097_152)
            throw new Error("Event frame exceeds console limit");
          const parsed = eventFrames(buffer);
          buffer = parsed.rest;
          for (const frame of parsed.frames) {
            const event = JSON.parse(frame.data);
            if (frame.event === "control")
              throw new ApiError(
                event.code === "unauthorized" ? 401 : 410,
                event.code,
                "Event connection needs to resume",
              );
            if (
              event.adm_id === adm &&
              Number.isSafeInteger(event.sequence) &&
              event.sequence > after
            ) {
              after = event.sequence;
              sessionStorage.setItem(key, String(after));
              changed();
            }
          }
        }
      } finally {
        await reader.cancel().catch(() => {});
      }
    } catch (error) {
      if (signal.aborted) break;
      if (error instanceof ApiError && error.status === 401) {
        window.dispatchEvent(new Event("adm-session-expired"));
        break;
      }
      if (error instanceof ApiError && error.code === "cursor_expired") {
        status("History expired · resynchronizing");
        try {
          const window = await api<{ earliest_cursor: number }>(
            `/adms/${adm}/event-window`,
            { signal },
          );
          after = window.earliest_cursor;
          sessionStorage.setItem(key, String(after));
          changed();
        } catch {
          failures++;
        }
      } else {
        failures++;
        status("Reconnecting · polling fallback");
        try {
          const page = await api<{ cursor: number; items: unknown[] }>(
            `/adms/${adm}/events?after=${after}`,
            { signal },
          );
          after = page.cursor;
          sessionStorage.setItem(key, String(after));
          changed();
        } catch {
          /* Retain cursor and retry, without re-submitting work. */
        }
      }
    }
    await pause();
  }
}
