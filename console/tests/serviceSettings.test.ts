import test from "node:test";
import assert from "node:assert/strict";
import { settingsDraft, settingsValues } from "../src/serviceSettings.ts";

const defaults = {
  llm_call: {
    max_input_tokens: 256000,
    max_output_tokens: 32768,
    max_duration_ms: 360000,
  },
  catalog_predicate_limit: 65536,
};
test("settings preserve exact ceilings and convert timeout units", () => {
  assert.equal(settingsDraft(defaults).seconds, "360");
  assert.deepEqual(settingsValues(settingsDraft(defaults)), defaults);
  const low = {
    llm_call: {
      max_input_tokens: 1,
      max_output_tokens: 1,
      max_duration_ms: 1001,
    },
    catalog_predicate_limit: 1,
  };
  assert.deepEqual(settingsValues(settingsDraft(low)), low);
});
test("invalid or out-of-range edits cannot become a save request", () => {
  const original = settingsDraft(defaults);
  for (const input of ["", " ", "0", "-1", "1.5", "1050001", "NaN", "Infinity"])
    assert.throws(() => settingsValues({ ...original, input }));
  for (const seconds of ["", "0", "601", "0.0001", "1.00001", "NaN"])
    assert.throws(() => settingsValues({ ...original, seconds }));
  assert.throws(() => settingsValues({ ...original, output: "100001" }));
  assert.throws(() => settingsValues({ ...original, predicates: "65537" }));
  assert.equal(
    settingsValues({ ...original, seconds: "0.001" }).llm_call.max_duration_ms,
    1,
  );
  assert.deepEqual(original, settingsDraft(defaults));
});
