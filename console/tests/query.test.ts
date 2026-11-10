import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import {
  callQuery,
  eventFrames,
  initial,
  parseJson,
  planQuery,
} from "../src/query.ts";

const declarations = (name: string) =>
  JSON.parse(
    readFileSync(
      new URL(`../../tests/fixtures/v1/models/${name}.json`, import.meta.url),
      "utf8",
    ),
  ).declarations;
test("forms follow two independent accepted vocabularies", () => {
  const tanks = declarations("tanks"),
    access = declarations("access");
  assert.deepEqual(initial({ ref: "tanks.State" }, tanks), {
    left: 0,
    right: 0,
  });
  assert.deepEqual(initial({ ref: "access.Permission" }, access), {
    tag: "closed",
    value: {},
  });
  assert.deepEqual(
    callQuery("evaluate", "tanks.space_left", tanks["tanks.space_left"], {
      state: { left: 2, right: 1 },
    }),
    {
      op: "evaluate",
      module: "tanks",
      expression: {
        op: "call",
        function: "tanks.space_left",
        args: {
          state: {
            op: "literal",
            value: { left: 2, right: 1 },
            type: { ref: "tanks.State" },
          },
        },
      },
    },
  );
  assert.deepEqual(
    callQuery("evaluate", "access.open", access["access.open"], {
      actor: "bob",
    }),
    {
      op: "evaluate",
      module: "access",
      expression: {
        op: "call",
        function: "access.open",
        args: {
          actor: { op: "literal", value: "bob", type: { ref: "access.Actor" } },
        },
      },
    },
  );
});
test("all actions, explicitly none, and a depth bound retain different meanings", () => {
  const all = planQuery("a.goal", {}, "all", [], "") as Record<string, unknown>;
  const none = planQuery("a.goal", {}, "explicit", [], "0") as Record<
    string,
    unknown
  >;
  assert.equal(Object.hasOwn(all, "transitions"), false);
  assert.equal(Object.hasOwn(all, "max_depth"), false);
  assert.deepEqual(none.transitions, []);
  assert.equal(none.max_depth, 0);
  assert.throws(() => planQuery("a.goal", {}, "all", [], "-1"));
});
test("strict JSON never normalizes duplicate keys or imprecise numbers into a different query", () => {
  for (const raw of [
    '{"a":1,"a":2}',
    '{"a":1,"\\u0061":2}',
    "1e999",
    "9007199254740993",
    '{"a":}',
    "[1,]",
    '{"x":NaN}',
    "true false",
    "[".repeat(34) + "]".repeat(34),
  ])
    assert.throws(() => parseJson(raw), raw);
  assert.equal(
    JSON.stringify(
      parseJson(
        '{"__proto__":{"polluted":true},"text":"<img src=x onerror=alert(1)>"}',
      ),
    ),
    '{"__proto__":{"polluted":true},"text":"<img src=x onerror=alert(1)>"}',
  );
  assert.equal(({} as { polluted?: boolean }).polluted, undefined);
});
test("event stream parsing handles chunk boundaries, heartbeat and control frames", () => {
  const text =
    ': keepalive\n\nid: a:1\nevent: request.received\ndata: {"sequence":1}\n\nevent: control\ndata: {"code":"cursor_expired"}\n\n';
  for (let split = 0; split <= text.length; split++) {
    const first = eventFrames(text.slice(0, split));
    const second = eventFrames(first.rest + text.slice(split));
    assert.deepEqual(
      [...first.frames, ...second.frames].map((f) => f.event),
      ["request.received", "control"],
    );
    assert.equal(second.rest, "");
  }
});
test("guided type recursion is bounded", () => {
  assert.throws(() =>
    initial(
      { ref: "a.Loop" },
      { "a.Loop": { kind: "type", type: { ref: "a.Loop" } } },
    ),
  );
  assert.throws(() =>
    initial({ kind: "vector", length: 1000, element: { kind: "bool" } }, {}),
  );
});
