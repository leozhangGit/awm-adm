import test from "node:test";
import assert from "node:assert/strict";
import {
  nextReference,
  newMessage,
  outcomeNote,
  replyText,
  savedMessage,
} from "../src/direct-chat.ts";
import type { Exchange } from "../src/direct-chat.ts";
const item = (id: string, status = "completed"): Exchange => ({
  id,
  status,
  text: "Question",
  origin: "console",
  channel: "ask",
  created_at_ms: 1,
  idempotency_key: id,
  reply: "Fallback",
  outcome_text: "Value: true",
  explanation: null,
  failure_code: null,
});
test("API activity cannot select another tab’s conversation context", () => {
  assert.equal(nextReference([item("mine"), item("api")], "mine"), "mine");
  assert.equal(nextReference([item("mine", "queued")], "mine"), null);
  assert.equal(nextReference([item("api")], null), null);
});
test("local checked outcome survives missing explanation", () => {
  assert.equal(replyText(item("a")), "Value: true");
  assert.equal(
    replyText({ ...item("a"), explanation: "You may borrow another item." }),
    "You may borrow another item.",
  );
});
test("a compact model value remains visible beside an explanation", () => {
  const row = {
    ...item("answer"),
    explanation: "You may borrow another item.",
    outcome_label: "Model answer: Yes",
  };
  assert.equal(outcomeNote(row), "Model answer: Yes");
  assert.equal(
    outcomeNote({ ...row, explanation: "No, you may not." }),
    "Model answer: Yes",
  );
  assert.equal(outcomeNote({ ...row, explanation: null }), null);
});
test("uncertain or complex outcomes are not hidden behind an AI explanation", () => {
  const row = {
    ...item("gap"),
    explanation: "Everything is fine.",
    outcome_text: "The model needs more information.",
    outcome_label: null,
  };
  assert.equal(outcomeNote(row), "The model needs more information.");
  assert.equal(outcomeNote({ ...row, explanation: row.outcome_text }), null);
});
test("successful teaching uses one explanation and a saved-outcome label", () => {
  const row = {
    ...item("learned"),
    channel: "teach",
    explanation: "The borrowing rule is ready.",
    outcome_text: "Learned and saved: the borrowing rule.",
    outcome_label: "Learned and saved · 1 objective",
  };
  assert.equal(replyText(row), row.explanation);
  assert.equal(outcomeNote(row), row.outcome_label);
  assert.equal(replyText({ ...row, explanation: null }), row.outcome_text);
});
test("an interrupted send retains its exact identity and reference", () => {
  const message = {
    idempotency_key: "same",
    text: "What about tomorrow?",
    attachments: [],
    reply_to: "prior",
  };
  assert.deepEqual(
    savedMessage({ getItem: () => JSON.stringify(message) }, "pending"),
    message,
  );
  assert.equal(savedMessage({ getItem: () => "{broken" }, "pending"), null);
  assert.equal(
    savedMessage({ getItem: () => '{"text":"incomplete"}' }, "pending"),
    null,
  );
});
test("Teach sends selected originals and an unchanged retry retains their identities", () => {
  const selected = ["history-file"];
  const message = newMessage(
    "teach",
    " Learn the supplied history. ",
    selected,
    null,
  );
  selected.push("unselected-after-send");
  assert.deepEqual(message.attachments, ["history-file"]);
  assert.deepEqual(
    savedMessage({ getItem: () => JSON.stringify(message) }, "pending"),
    message,
  );
  assert.deepEqual(
    newMessage("ask", "What is known?", selected, "prior").attachments,
    [],
  );
});
