import assert from "node:assert/strict";
import { test } from "node:test";
import {
  providerBlock,
  providerFailureText,
  submissionError,
} from "../src/feedback.ts";

test("provider readiness needs both purpose and installation authority; recorded stays offline", () => {
  const c = {
    provider: "openai",
    enabled: true,
    status: "ready",
    purposes: ["interpretation"],
  };
  assert.match(
    providerBlock(c, { remote_calls_enabled: false }, "interpretation")!,
    /Remote calls are disabled/,
  );
  assert.equal(
    providerBlock(c, { remote_calls_enabled: true }, "interpretation"),
    null,
  );
  assert.equal(
    providerBlock(
      { ...c, provider: "recorded" },
      { remote_calls_enabled: false },
      "interpretation",
    ),
    null,
  );
  assert.match(
    providerBlock(c, { remote_calls_enabled: true }, "extraction")!,
    /does not permit/,
  );
  assert.match(
    providerBlock(
      { ...c, status: "credential_unavailable" },
      { remote_calls_enabled: true },
      "interpretation",
    )!,
    /not ready/,
  );
  assert.match(providerBlock(c, null, "interpretation")!, /not loaded/);
});

test("provider failure explains incomplete output without inferring credits or retrying", () => {
  const failed = {
    id: "authored-grant",
    status: "failed",
    unresolved: true,
    input_tokens: 20000,
    output_tokens: 4096,
    outcome: {
      error: "output_incomplete",
      diagnostics: {
        incomplete_reason: "max_output_tokens",
        usage_assessment: "zero_unverified",
        reported_usage: { input_tokens: 0, output_tokens: 0 },
      },
    },
  };
  const message = providerFailureText(failed).join(" ");
  assert.match(message, /output-token limit/);
  assert.match(message, /not proof of a free call/);
  assert.match(message, /reservation retained/);
  assert.match(message, /No automatic retry/);
  assert.doesNotMatch(message, /insufficient quota/);
  assert.match(
    providerFailureText({
      ...failed,
      outcome: { error: "output_incomplete" },
    }).join(" "),
    /not retained or supplied/,
  );
  assert.match(
    providerFailureText({
      ...failed,
      outcome: { error: "provider_quota_exhausted" },
    }).join(" "),
    /insufficient quota/,
  );
  assert.match(
    providerFailureText({ ...failed, outcome: { error: "rate_limited" } }).join(
      " ",
    ),
    /HTTP 429/,
  );
});

test("configuration failures do not suggest unchanged retries, uncertain transport does", () => {
  for (const code of [
    "forbidden",
    "remote_calls_disabled",
    "invalid_input",
    "stale_context",
    "conflict",
  ]) {
    assert.doesNotMatch(
      submissionError({ code, message: "Authored error", status: 403 }),
      /retry the unchanged/,
    );
  }
  assert.match(
    submissionError(new TypeError("Connection lost")),
    /outcome may be unknown/,
  );
  assert.match(
    submissionError({
      code: "internal_error",
      message: "Could not complete",
      status: 503,
    }),
    /retry the unchanged/,
  );
  assert.doesNotMatch(
    submissionError(new SyntaxError("Invalid JSON")),
    /retry the unchanged/,
  );
});

test("response metadata distinguishes reported zeros from missing details", () => {
  const failure = {
    id: "authored-metadata-grant",
    status: "failed",
    unresolved: true,
    input_tokens: 8536,
    output_tokens: 8192,
    outcome: {
      error: "output_incomplete",
      diagnostics: {
        reasoning_effort: "none",
        token_details: { reasoning_tokens: 0 },
        output_summary: {
          item_count: 1,
          message_items: 1,
          text_items: 0,
          reasoning_items: 0,
          other_items: 0,
          visible_text_parts: 1,
          visible_text_bytes: 15,
        },
      },
    },
  };
  const message = providerFailureText(failure).join(" ");
  assert.match(message, /reasoning effort none; 0 reasoning tokens/);
  assert.match(message, /15 bytes of visible text/);
  assert.match(message, /reservation retained/);
  const historical = providerFailureText({
    ...failure,
    outcome: { error: "output_incomplete" },
  }).join(" ");
  assert.doesNotMatch(
    historical,
    /reasoning effort|reasoning tokens|bytes of visible text/,
  );
});
