import assert from "node:assert/strict";
import { test } from "node:test";
import { readFileSync } from "node:fs";
import { intentLines, suggestions } from "../src/language.ts";

test("language templates derive from two independent catalogs without fixture branches", () => {
  for (const name of ["tanks", "access"]) {
    const d = JSON.parse(
      readFileSync(
        new URL(`../../tests/fixtures/v1/models/${name}.json`, import.meta.url),
        "utf8",
      ),
    ).declarations;
    const phrases = suggestions(d);
    assert.equal(phrases[0], "What can you do?");
    assert.ok(phrases.some((p) => p.includes(name + ".")));
    assert.ok(phrases.length <= 9);
  }
  assert.deepEqual(suggestions({}), ["What can you do?"]);
});

test("preview distinguishes all actions, no actions, bounded depth and literal arguments", () => {
  const q = {
    op: "find_plan",
    module: "site",
    goal: "site.done",
    initial_state: 0,
    transitions: null,
    max_depth: null,
  };
  assert.ok(
    intentLines(q).includes("Use all accepted actions in this module."),
  );
  assert.ok(
    intentLines({ ...q, transitions: [] }).includes(
      "Use no actions (explicit empty selection).",
    ),
  );
  assert.ok(
    intentLines({ ...q, max_depth: 0 }).includes("Search at most 0 steps."),
  );
  assert.deepEqual(
    intentLines({
      op: "evaluate",
      module: "site",
      expression: {
        op: "call",
        function: "site.available",
        args: {
          year: {
            op: "literal",
            value: 2024,
            type: { kind: "int", min: 2020, max: 2025 },
          },
        },
      },
    }),
    ["Evaluate site.available.", 'Arguments: {"year":2024}.'],
  );
});
