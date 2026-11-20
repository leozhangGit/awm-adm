import test from "node:test";
import assert from "node:assert/strict";
import { chatPages, mergeExchanges } from "../src/chat-pages.ts";
import type { Exchange } from "../src/direct-chat.ts";

const row = (sequence: number): Exchange => ({
  id: String(sequence),
  sequence,
  idempotency_key: String(sequence),
  channel: "ask",
  origin: "console",
  created_at_ms: sequence,
  status: "completed",
  text: "Saved question",
  reply: "Saved answer",
  outcome_text: null,
  explanation: null,
  failure_code: null,
});
function fixture(count = 205) {
  const records = Array.from({ length: count }, (_, i) => row(i + 1));
  const queries: string[] = [];
  let visible: Exchange[] = [],
    more = false,
    fail = false;
  const pages = chatPages(
    async (query) => {
      queries.push(query);
      if (fail) throw new Error("Offline");
      const p = new URLSearchParams(query);
      const backward = p.get("direction") === "backward";
      const sorted = backward
        ? records
            .filter((r) => r.sequence < Number(p.get("before") || Infinity))
            .toReversed()
        : records.filter((r) => r.sequence > Number(p.get("after") || 0));
      const selected = sorted.slice(0, 100);
      return {
        items: backward ? selected.toReversed() : selected,
        next_cursor: selected.at(-1)?.sequence ?? 0,
        has_more: sorted.length > 100,
      };
    },
    (items, hasOlder) => {
      visible = mergeExchanges(visible, items);
      more = hasOlder;
    },
  );
  return {
    pages,
    records,
    queries,
    visible: () => visible,
    more: () => more,
    fail: (v: boolean) => {
      fail = v;
    },
  };
}

test("open shows only latest 100; each explicit load adds at most 100 older exchanges", async () => {
  const f = fixture();
  await f.pages.refresh();
  assert.equal(f.queries.length, 1);
  assert.deepEqual(
    f.visible().map((r) => r.sequence),
    Array.from({ length: 100 }, (_, i) => i + 106),
  );
  assert.equal(f.more(), true);
  f.records.push(row(206));
  await f.pages.refresh();
  assert.equal(f.visible()[0].sequence, 106);
  assert.equal(f.visible().length, 101);
  let anchored = 0;
  await f.pages.older(() => anchored++);
  assert.equal(f.visible()[0].sequence, 6);
  assert.equal(f.visible().length, 201);
  await f.pages.refresh();
  assert.equal(f.visible()[0].sequence, 6);
  await f.pages.older(() => anchored++);
  assert.equal(f.visible().length, 206);
  assert.equal(f.more(), false);
  assert.equal(anchored, 2);
  await f.pages.older(() => anchored++);
  assert.equal(anchored, 2);
});

test("failed older loads retain their cursor and retries neither skip nor duplicate", async () => {
  const f = fixture();
  await f.pages.refresh();
  f.fail(true);
  await assert.rejects(
    f.pages.older(() => assert.fail("No prepend on failure")),
    /Offline/,
  );
  assert.equal(f.visible().length, 100);
  assert.equal(f.more(), true);
  f.fail(false);
  await f.pages.older(() => {});
  assert.equal(f.visible().length, 200);
  assert.equal(f.queries.at(-1), f.queries.at(-2));
});

test("serialized polling and older loads retain updates and empty histories load their first message", async () => {
  const empty = fixture(0);
  await empty.pages.refresh();
  assert.equal(empty.more(), false);
  empty.records.push(row(1));
  await empty.pages.refresh();
  assert.equal(empty.visible().length, 1);
  const f = fixture();
  await f.pages.refresh();
  f.records[150] = { ...f.records[150], reply: "Completed later" };
  await Promise.all([f.pages.older(() => {}), f.pages.refresh()]);
  assert.equal(f.visible().length, 200);
  assert.equal(
    f.visible().find((r) => r.sequence === 151)?.reply,
    "Completed later",
  );
  assert.equal(f.queries.at(-2), "after=5&limit=100");
});

test("merging poll results preserves a just-submitted exchange and stable chronological order", () => {
  const current = [row(10), row(11)];
  assert.equal(mergeExchanges(current, [row(10)]), current);
  assert.deepEqual(
    mergeExchanges(current, [row(9)]).map((r) => r.sequence),
    [9, 10, 11],
  );
});
