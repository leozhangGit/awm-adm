import assert from "node:assert/strict";
import { test } from "node:test";
import { api } from "../src/api.ts";

test("console API uses no cookies, authorization or CSRF credential", async () => {
  const original = globalThis.fetch;
  globalThis.fetch = async (url, options) => {
    assert.equal(url, "/api/v1/adms");
    assert.equal(options?.credentials, "omit");
    const headers = options?.headers as Record<string, string>;
    assert.equal(headers.Authorization, undefined);
    assert.equal(headers["X-CSRF-Token"], undefined);
    assert.equal(headers["X-ADM-Client"], "console");
    return new Response(JSON.stringify({ items: [] }), { status: 200 });
  };
  try {
    assert.deepEqual((await api<{ items: unknown[] }>("/adms")).items, []);
  } finally {
    globalThis.fetch = original;
  }
});
