import { test } from "node:test";
import assert from "node:assert/strict";
import { readDraft, saveDraft } from "../src/draft.ts";

test("tab drafts restore text without crossing model/channel scope or authorizing submission", () => {
  const data = new Map<string, string>();
  const storage = {
    getItem: (k: string) => data.get(k) || null,
    setItem: (k: string, v: string) => {
      data.set(k, v);
    },
    removeItem: (k: string) => {
      data.delete(k);
    },
  };
  saveDraft(storage, "model:ask:conversation", "An unsent question");
  assert.equal(
    readDraft(storage, "model:ask:conversation"),
    "An unsent question",
  );
  assert.equal(readDraft(storage, "model:teach:conversation"), "");
  assert.equal(readDraft(storage, "other:ask:conversation"), "");
  assert.equal(data.size, 1);
  saveDraft(storage, "model:ask:conversation", "");
  assert.equal(data.size, 0);
});

test("unavailable storage and oversized retained drafts fail closed", () => {
  assert.equal(readDraft({ getItem: () => "x".repeat(16385) }, "draft"), "");
  assert.equal(
    readDraft(
      {
        getItem: () => {
          throw Error("disabled");
        },
      },
      "draft",
    ),
    "",
  );
  assert.doesNotThrow(() =>
    saveDraft(
      {
        setItem: () => {
          throw Error("full");
        },
        removeItem: () => {},
      },
      "draft",
      "text",
    ),
  );
});
