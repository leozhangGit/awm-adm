/** Bounded recovery guidance; this module never resubmits or changes an identity. */
export function submissionError(error: unknown): string {
  const value = error as {
    message?: string;
    code?: string;
    status?: number;
    name?: string;
  };
  const message = value?.message || "The operation could not complete.";
  if (value?.code === "unauthorized")
    return `${message}. Sign in again before continuing.`;
  if (value?.code === "remote_calls_disabled") return message;
  if (value?.code === "stale_context")
    return `${message}. Reload and review the current model or connection before submitting.`;
  if (value?.code === "conflict")
    return `${message}. Inspect the recorded operation before creating a new submission.`;
  if (
    ["busy", "quota_exceeded", "resource_exhausted"].includes(value?.code || "")
  )
    return `${message}. Inspect capacity and pending work before retrying; limits are not increased automatically.`;
  if (
    (value?.status && value.status >= 500) ||
    ["TypeError", "TimeoutError", "AbortError"].includes(value?.name || "")
  )
    return `${message}. The outcome may be unknown. Inspect the existing request or retry the unchanged submission to recover its recorded outcome.`;
  return message;
}

export type ProviderChoice = {
  provider: string;
  enabled: boolean;
  status: string;
  purposes: string[];
};
export function providerBlock(
  selected: ProviderChoice | undefined,
  settings: { remote_calls_enabled: boolean } | null,
  purpose: string,
): string | null {
  if (!settings)
    return "Provider availability has not loaded. Refresh before submitting.";
  if (!selected) return "Choose a connection for this operation.";
  if (!selected.enabled)
    return "This connection is disabled. Review it in Connections.";
  if (!selected.purposes.includes(purpose))
    return `This connection does not permit ${purpose}. Review its purposes in Connections.`;
  if (selected.status !== "ready")
    return "This connection is not ready. Review its credential and gateway status in Connections.";
  if (selected.provider !== "recorded" && !settings.remote_calls_enabled)
    return "Remote calls are disabled for this installation. Review the global allowance in Connections.";
  return null;
}

export type ProviderFailureView = {
  id: string;
  status: string;
  unresolved: boolean;
  input_tokens: number;
  output_tokens: number;
  outcome: {
    error?: string | null;
    response_id?: string | null;
    returned_model?: string | null;
    diagnostics?: {
      incomplete_reason?: string | null;
      http_status?: number | null;
      provider_error_code?: string | null;
      usage_assessment?: string | null;
      reported_usage?: { input_tokens: number; output_tokens: number } | null;
      reasoning_effort?: string | null;
      reasoning_mode?: string | null;
      token_details?: {
        reasoning_tokens?: number | null;
        cached_input_tokens?: number | null;
        total_tokens?: number | null;
        cache_creation_input_tokens?: number | null;
        cache_read_input_tokens?: number | null;
      } | null;
      output_summary?: {
        item_count: number;
        message_items: number;
        text_items: number;
        reasoning_items: number;
        other_items: number;
        visible_text_parts: number;
        visible_text_bytes: number;
      } | null;
    } | null;
  };
};

export function providerFailureText(failure: ProviderFailureView): string[] {
  const code = failure.outcome.error;
  const diagnostic = failure.outcome.diagnostics;
  const reasons: Record<string, string> = {
    max_output_tokens:
      "The provider reported that the output-token limit was reached.",
    content_filter:
      "The provider reported that a content filter stopped the output.",
    steered: "The provider reported that steering stopped this response.",
  };
  const messages: Record<string, string> = {
    provider_quota_exhausted:
      "The provider reported insufficient quota. Check the provider project's billing and spending limits.",
    rate_limited: ["rate_limit_exceeded", "rate_limit_error"].includes(
      diagnostic?.provider_error_code || "",
    )
      ? "The provider rejected this call because of a rate limit."
      : "The provider returned HTTP 429 (rate or quota limit). A more precise provider code was not supplied in a supported form.",
    authentication_failed:
      "The provider rejected the connection's authentication or access permissions.",
    unsupported_or_invalid_request:
      "The provider rejected the model or request format.",
    refusal: "The provider declined to produce the requested output.",
    transport_uncertain:
      "The call's outcome is unknown because the connection or deadline was interrupted.",
    provider_error: "The provider returned an HTTP error.",
    invalid_response: "The provider response could not be validated.",
  };
  const result = [
    code === "output_incomplete"
      ? `Provider response incomplete. ${reasons[diagnostic?.incomplete_reason || ""] || "The detailed reason was not retained or supplied in a supported form."}`
      : messages[code || ""] ||
        "The provider call did not complete successfully. Inspect its recorded details.",
  ];
  if (diagnostic?.usage_assessment === "zero_unverified") {
    result.push(
      "The provider reported 0 input and 0 output tokens. This is unverified usage, not proof of a free call.",
    );
  }
  const reported = [];
  if (diagnostic?.reasoning_effort != null)
    reported.push(`reasoning effort ${diagnostic.reasoning_effort}`);
  if (diagnostic?.reasoning_mode != null)
    reported.push(`reasoning mode ${diagnostic.reasoning_mode}`);
  if (diagnostic?.token_details?.reasoning_tokens != null)
    reported.push(
      `${diagnostic.token_details.reasoning_tokens.toLocaleString()} reasoning tokens`,
    );
  if (reported.length)
    result.push(`Provider-reported details: ${reported.join("; ")}.`);
  const output = diagnostic?.output_summary;
  if (output) {
    result.push(
      `Response contained ${output.item_count.toLocaleString()} output items, including ${output.reasoning_items.toLocaleString()} reasoning items, and ${output.visible_text_bytes.toLocaleString()} bytes of visible text in ${output.visible_text_parts.toLocaleString()} text parts. These counts do not include hidden reasoning content.`,
    );
  }
  if (failure.unresolved) {
    result.push(
      `Token reservation retained: ${failure.input_tokens.toLocaleString()} input and ${failure.output_tokens.toLocaleString()} output. Usage has not been settled.`,
    );
  }
  result.push(
    "No automatic retry. Review this failure before starting another call.",
  );
  return result;
}
