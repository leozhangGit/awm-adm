import assert from "node:assert/strict";
import { test } from "node:test";
import { api, authApi, saveSession, session } from "../src/api.ts";

test("administrator CSRF stays in memory and failed password entry keeps the account screen", async () => {
  const previousFetch = globalThis.fetch;
  const previousWindow = Object.getOwnPropertyDescriptor(globalThis, "window");
  const events = new EventTarget();
  let expired = 0;
  events.addEventListener("adm-session-expired", () => expired++);
  Object.defineProperty(globalThis, "window", {
    value: events,
    configurable: true,
  });
  saveSession({ id: "synthetic-session", csrf: "synthetic-csrf" });
  try {
    globalThis.fetch = async (url, options) => {
      assert.equal(url, "/api/v1/auth/password");
      assert.equal(options?.credentials, "same-origin");
      assert.equal(
        (options?.headers as Record<string, string>)["X-CSRF-Token"],
        "synthetic-csrf",
      );
      assert.equal(
        (options?.headers as Record<string, string>).Authorization,
        undefined,
      );
      return new Response(
        JSON.stringify({
          code: "unauthorized",
          message: "Invalid credentials",
        }),
        { status: 401 },
      );
    };
    await assert.rejects(
      authApi("/password", {
        current_password: "wrong",
        new_password: "synthetic new passphrase",
      }),
    );
    assert.equal(expired, 0);
    assert.equal(session()?.id, "synthetic-session");
    globalThis.fetch = async () =>
      new Response(
        JSON.stringify({ code: "unauthorized", message: "Expired session" }),
        { status: 401 },
      );
    await assert.rejects(authApi("/me"));
    assert.equal(expired, 1);
    await assert.rejects(api("/auth/tokens", { method: "POST", body: {} }));
    assert.equal(expired, 2);
    await assert.rejects(api("/adms"));
    assert.equal(expired, 3);
    saveSession(null);
    assert.equal(session(), null);
  } finally {
    saveSession(null);
    globalThis.fetch = previousFetch;
    if (previousWindow)
      Object.defineProperty(globalThis, "window", previousWindow);
    else Reflect.deleteProperty(globalThis, "window");
  }
});
