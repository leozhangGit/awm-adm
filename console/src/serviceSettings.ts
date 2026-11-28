export type ServiceValues = {
  llm_call: {
    max_input_tokens: number;
    max_output_tokens: number;
    max_duration_ms: number;
  };
  catalog_predicate_limit: number;
};
export type ServiceSettingsReply = {
  revision: number;
  values: ServiceValues;
  defaults: ServiceValues;
};
export type SettingsDraft = {
  input: string;
  output: string;
  seconds: string;
  predicates: string;
};
export function settingsDraft(value: ServiceValues): SettingsDraft {
  return {
    input: String(value.llm_call.max_input_tokens),
    output: String(value.llm_call.max_output_tokens),
    seconds: String(value.llm_call.max_duration_ms / 1000),
    predicates: String(value.catalog_predicate_limit),
  };
}
export function settingsValues(draft: SettingsDraft): ServiceValues {
  const integer = (raw: string, name: string, max: number) => {
    const n = Number(raw);
    if (!raw.trim() || !Number.isSafeInteger(n) || n < 1 || n > max)
      throw new Error(
        `${name} must be a whole number from 1 to ${max.toLocaleString("en-US")}.`,
      );
    return n;
  };
  const seconds = Number(draft.seconds);
  const ms = Math.round(seconds * 1000);
  if (
    !draft.seconds.trim() ||
    !Number.isFinite(seconds) ||
    ms < 1 ||
    ms > 600000 ||
    Math.abs(seconds * 1000 - ms) > 0.000001
  )
    throw new Error(
      "Provider timeout must be from 0.001 to 600 seconds, with at most three decimal places.",
    );
  return {
    llm_call: {
      max_input_tokens: integer(
        draft.input,
        "Input reservation ceiling",
        1050000,
      ),
      max_output_tokens: integer(draft.output, "Output token ceiling", 100000),
      max_duration_ms: ms,
    },
    catalog_predicate_limit: integer(draft.predicates, "Predicate cap", 65536),
  };
}
