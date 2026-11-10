import assert from "node:assert/strict";
import { test } from "node:test";
import { watch, saveSession } from "../src/api.ts";

function storage() {
  const values = new Map<string, string>();
  return {
    getItem: (k: string) => values.get(k) || null,
    setItem: (k: string, v: string) => values.set(k, v),
    removeItem: (k: string) => values.delete(k),
  };
}
function environment() {
  const previous = {
    fetch: globalThis.fetch,
    local: Object.getOwnPropertyDescriptor(globalThis, "localStorage"),
    session: Object.getOwnPropertyDescriptor(globalThis, "sessionStorage"),
    window: Object.getOwnPropertyDescriptor(globalThis, "window"),
  };
  const local = storage(),
    saved = storage(),
    window = new EventTarget();
  saveSession({ id: "session-a", csrf: "test-only" });
  for (const [key, value] of Object.entries({
    localStorage: local,
    sessionStorage: saved,
    window,
  }))
    Object.defineProperty(globalThis, key, { value, configurable: true });
  return {
    saved,
    window,
    restore: () => {
      saveSession(null);
      globalThis.fetch = previous.fetch;
      for (const [key, descriptor] of [
        ["localStorage", previous.local],
        ["sessionStorage", previous.session],
        ["window", previous.window],
      ] as const) {
        if (descriptor) Object.defineProperty(globalThis, key, descriptor);
        else Reflect.deleteProperty(globalThis, key);
      }
    },
  };
}
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), {
    status,
    headers: { "Content-Type": "application/json" },
  });
test("an expired event cursor resynchronizes resources and resumes without submitting work", async () => {
  const env = environment(),
    controller = new AbortController(),
    calls: string[] = [],
    states: string[] = [];
  let changes = 0;
  globalThis.fetch = async (input) => {
    const url = String(input);
    calls.push(url);
    if (url.endsWith("/event-window")) return json({ earliest_cursor: 10 });
    if (url.includes("after=0"))
      return json({ code: "cursor_expired", message: "expired" }, 410);
    assert.match(url, /after=10/);
    return new Response(
      'id: a:11\nevent: request.succeeded\ndata: {"adm_id":"a","sequence":11}\n\n',
    );
  };
  try {
    await watch(
      "a",
      controller.signal,
      () => {
        if (++changes === 2) controller.abort();
      },
      (s) => states.push(s),
    );
    assert.equal(env.saved.getItem("adm-events:session-a:a"), "11");
    assert.ok(states.includes("History expired · resynchronizing"));
    assert.equal(calls.length, 3);
    assert.ok(calls.every((path) => !path.includes("/requests")));
  } finally {
    env.restore();
  }
});
test("ADM cursors are independent and duplicate events do not trigger duplicate refreshes", async () => {
  const env = environment();
  try {
    for (const adm of ["a", "b"]) {
      const controller = new AbortController();
      let refreshes = 0;
      globalThis.fetch = async () =>
        new Response(
          `id: ${adm}:1\nevent: request.received\ndata: {"adm_id":"${adm}","sequence":1}\n\nid: ${adm}:1\nevent: request.received\ndata: {"adm_id":"${adm}","sequence":1}\n\n`,
        );
      await watch(
        adm,
        controller.signal,
        () => {
          refreshes++;
          controller.abort();
        },
        () => {},
      );
      assert.equal(refreshes, 1);
    }
    assert.equal(env.saved.getItem("adm-events:session-a:a"), "1");
    assert.equal(env.saved.getItem("adm-events:session-a:b"), "1");
  } finally {
    env.restore();
  }
});
test("expired authentication stops reconnecting and returns to login", async () => {
  const env = environment();
  let calls = 0,
    expired = 0;
  env.window.addEventListener("adm-session-expired", () => expired++);
  globalThis.fetch = async () => {
    calls++;
    return json({ code: "unauthorized", message: "expired" }, 401);
  };
  try {
    await watch(
      "a",
      new AbortController().signal,
      () => assert.fail(),
      () => {},
    );
    assert.equal(expired, 1);
    assert.equal(calls, 1);
  } finally {
    env.restore();
  }
});
