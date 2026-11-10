import { test } from "node:test";
import assert from "node:assert/strict";
import {
  inlineParts,
  workLabel,
  dollars,
  sameContext,
  microUsd,
  recoveryAdvice,
} from "../src/chat.ts";

test("rich text has no executable HTML, link or image token", () => {
  const attack =
    "<script>alert(1)</script> ![remote](https://evil.example/x) [go](javascript:alert(1))";
  assert.deepEqual(inlineParts(attack), [{ kind: "text", text: attack }]);
  assert.deepEqual(inlineParts("A **bound value** and `code`"), [
    { kind: "text", text: "A " },
    { kind: "strong", text: "bound value" },
    { kind: "text", text: " and " },
    { kind: "code", text: "code" },
  ]);
});
test("queued work is never called active; unsupported is never a model answer", () => {
  assert.equal(
    workLabel({ status: "awaiting_provider", dispatch_status: "ready" }),
    "Queued for a provider worker",
  );
  assert.equal(
    workLabel({ status: "awaiting_provider", dispatch_status: "dispatched" }),
    "Working on clarification",
  );
  assert.match(workLabel({ status: "unavailable" }), /not available/);
  assert.match(workLabel({ status: "interrupted" }), /no automatic retry/);
  assert.equal(dollars(500000), "$0.50");
});

test("context comparison ignores object key order, not field values", () => {
  assert.equal(
    sameContext({ adm: "a", epoch: 2 }, { epoch: 2, adm: "a" }),
    true,
  );
  assert.equal(
    sameContext({ adm: "a", epoch: 2 }, { epoch: 3, adm: "a" }),
    false,
  );
  assert.equal(sameContext({ adm: "a" }, { adm: "a", epoch: 2 }), false);
});

test("Ask progress distinguishes queued interpretation, local work and narration", () => {
  assert.equal(
    workLabel({
      status: "awaiting_provider",
      flow: "ask",
      dispatch_status: "dispatched",
    }),
    "Interpreting your question",
  );
  assert.equal(
    workLabel({ status: "awaiting_local" }),
    "Local request submitted",
  );
  assert.equal(
    workLabel({ status: "awaiting_narration", dispatch_status: "ready" }),
    "Outcome saved · explanation queued",
  );
  assert.equal(workLabel({ status: "completed" }), "Outcome ready");
  assert.equal(
    workLabel({ status: "needs_learning" }),
    "Model knowledge needed",
  );
});

test("money parsing preserves microdollars without rounding or exponent shortcuts", () => {
  assert.equal(microUsd("0.000001"), 1);
  assert.equal(microUsd("12.345678"), 12345678);
  assert.equal(microUsd("1000"), 1000000000);
  for (const input of [
    "1e2",
    "-1",
    "0.0000001",
    "1000.000001",
    "NaN",
    "",
    "1,000",
  ])
    assert.throws(() => microUsd(input));
});

test("recovery advice does not imply a retry repairs authority or refunds uncertainty", () => {
  assert.match(recoveryAdvice("stale_context"), /cannot renew/);
  assert.match(recoveryAdvice("forbidden"), /does not grant access/);
  assert.match(recoveryAdvice("quota_exceeded"), /uncertain usage/);
  assert.match(recoveryAdvice(), /no automatic retry/);
});
