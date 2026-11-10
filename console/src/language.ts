import type { Json, Declaration } from "./types.ts";
import { initial } from "./query.ts";

// These describe an interpretation, never an answer or evidence.
export function intentLines(query: Record<string, Json>): string[] {
  const expr = (query.expression || query.proposition) as
    | Record<string, Json>
    | undefined;
  if (query.op === "capabilities")
    return ["List this ADM's accepted capabilities."];
  if (query.op === "explain")
    return [`Explain recorded local result ${query.result_id}.`];
  if (query.op === "find_plan")
    return [
      `Find a plan for ${query.goal} in ${query.module}.`,
      `Start from ${JSON.stringify(query.initial_state)}.`,
      query.transitions === null
        ? "Use all accepted actions in this module."
        : Array.isArray(query.transitions) && query.transitions.length === 0
          ? "Use no actions (explicit empty selection)."
          : `Use only ${JSON.stringify(query.transitions)}.`,
      query.max_depth === null
        ? "No explicit depth cutoff; local work, time and memory limits still apply."
        : `Search at most ${query.max_depth} steps.`,
    ];
  if (expr?.op === "call")
    return [
      `${query.op === "check_claim" ? "Check the Boolean claim" : "Evaluate"} ${expr.function}.`,
      `Arguments: ${JSON.stringify(Object.fromEntries(Object.entries((expr.args || {}) as Record<string, Record<string, Json>>).map(([name, arg]) => [name, arg.op === "literal" ? arg.value : arg])))}.`,
    ];
  return [
    `Check a Boolean expression in ${query.module}: ${JSON.stringify(expr)}.`,
  ];
}

export function suggestions(
  declarations: Record<string, Declaration>,
): string[] {
  const phrases = ["What can you do?"];
  for (const [symbol, d] of Object.entries(declarations)) {
    if (phrases.length >= 9) break;
    try {
      if (d.kind === "function") {
        const params = Object.entries(d.params || {});
        phrases.push(
          params.length
            ? `evaluate ${symbol} with ${JSON.stringify(Object.fromEntries(params.map(([name, t]) => [name, initial(t, declarations)])))}`
            : `What is ${symbol}?`,
        );
      } else if (d.kind === "goal" && d.state) {
        phrases.push(
          `plan ${symbol.slice(0, symbol.lastIndexOf("."))} to ${symbol} from ${JSON.stringify(initial(d.state, declarations))}`,
        );
      }
    } catch {
      /* A type outside the bounded form profile needs explicit input. */
    }
  }
  return phrases;
}
