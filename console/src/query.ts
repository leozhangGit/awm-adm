import type { Declaration, Json, Spec } from "./types.ts";

export function resolve(
  spec: Spec,
  declarations: Record<string, Declaration>,
  depth = 0,
): Spec {
  if (depth > 16)
    throw new Error(
      "This type is too deeply nested for a guided form. Use JSON.",
    );
  if (spec.ref) {
    const found = declarations[spec.ref]?.type;
    if (!found) throw new Error(`Type ${spec.ref} is unavailable.`);
    return resolve(found, declarations, depth + 1);
  }
  return spec;
}
export function initial(
  spec: Spec,
  declarations: Record<string, Declaration>,
  depth = 0,
): Json {
  if (depth > 12) throw new Error("Use JSON for deeply nested values.");
  const t = resolve(spec, declarations);
  if (t.kind === "refined") return initial(t.base!, declarations, depth + 1);
  if (t.kind === "bool") return false;
  if (t.kind === "int") return t.min!;
  if (t.kind === "enum") return t.values![0];
  if (t.kind === "record")
    return Object.fromEntries(
      Object.entries(t.fields!).map(([k, v]) => [
        k,
        initial(v, declarations, depth + 1),
      ]),
    );
  if (t.kind === "sum") {
    const [tag, child] = Object.entries(t.variants!)[0];
    return { tag, value: initial(child, declarations, depth + 1) };
  }
  if (t.kind === "vector" && t.length! <= 64)
    return Array.from({ length: t.length! }, () =>
      initial(t.element!, declarations, depth + 1),
    );
  throw new Error("This type requires the JSON editor.");
}
export function callQuery(
  op: string,
  symbol: string,
  declaration: Declaration,
  args: Record<string, Json>,
): Json {
  const call = {
    op: "call",
    function: symbol,
    args: Object.fromEntries(
      Object.entries(declaration.params || {}).map(([key, type]) => [
        key,
        { op: "literal", value: args[key], type },
      ]),
    ),
  };
  return {
    op,
    module: symbol.slice(0, symbol.lastIndexOf(".")),
    [op === "evaluate" ? "expression" : "proposition"]: call,
  };
}
export function planQuery(
  goal: string,
  state: Json,
  selection: "all" | "explicit",
  actions: string[],
  depth: string,
): Json {
  const result: Record<string, Json> = {
    op: "find_plan",
    module: goal.slice(0, goal.lastIndexOf(".")),
    goal,
    initial_state: state,
  };
  if (selection === "explicit") result.transitions = [...actions];
  if (depth !== "") {
    const n = Number(depth);
    if (!Number.isSafeInteger(n) || n < 0)
      throw new Error("Depth must be a nonnegative integer.");
    result.max_depth = n;
  }
  return result;
}
export function parseJson(text: string): Json {
  if (new TextEncoder().encode(text).length > 2_000_000)
    throw new Error("JSON exceeds the console limit of 2 MB.");
  let pos = 0,
    nodes = 0;
  const white = () => {
    while (/[ \t\r\n]/.test(text[pos] || "x") && pos < text.length) pos++;
  };
  const string = () => {
    const begin = pos++;
    while (pos < text.length) {
      if (text[pos] === "\\") {
        pos += 2;
        continue;
      }
      if (text[pos++] === '"')
        return JSON.parse(text.slice(begin, pos)) as string;
    }
    throw Error("Unclosed JSON string.");
  };
  function value(depth: number): Json {
    if (depth > 32 || ++nodes > 100_000)
      throw Error("JSON exceeds structural limits.");
    white();
    const c = text[pos];
    if (c === '"') return string();
    if (c === "{" || c === "[") {
      pos++;
      white();
      const end = c === "{" ? "}" : "]",
        object: Record<string, Json> = Object.create(null),
        array: Json[] = [];
      if (text[pos] === end) {
        pos++;
        return c === "{" ? object : array;
      }
      while (pos < text.length) {
        white();
        if (c === "{") {
          if (text[pos] !== '"') throw Error("Expected a JSON property name.");
          const key = string();
          if (Object.hasOwn(object, key))
            throw Error("Duplicate JSON property: " + key);
          white();
          if (text[pos++] !== ":") throw Error("Expected a colon.");
          object[key] = value(depth + 1);
        } else array.push(value(depth + 1));
        white();
        const next = text[pos++];
        if (next === end) return c === "{" ? object : array;
        if (next !== ",") throw Error("Expected a comma or closing bracket.");
      }
      throw Error("Unclosed JSON structure.");
    }
    for (const [word, result] of [
      ["true", true],
      ["false", false],
      ["null", null],
    ] as const) {
      if (text.startsWith(word, pos)) {
        pos += word.length;
        return result;
      }
    }
    const match = text
      .slice(pos)
      .match(/^-?(?:0|[1-9]\d*)(?:\.\d+)?(?:[eE][+-]?\d+)?/);
    if (!match) throw Error("Invalid JSON value.");
    pos += match[0].length;
    const n = Number(match[0]);
    if (
      !Number.isFinite(n) ||
      (Number.isInteger(n) && !Number.isSafeInteger(n))
    )
      throw Error("Number cannot be represented exactly by this console.");
    return n;
  }
  const result = value(0);
  white();
  if (pos !== text.length) throw Error("Unexpected content after JSON.");
  return result;
}
export function eventFrames(buffer: string): {
  frames: { event: string; id: string; data: string }[];
  rest: string;
} {
  const parts = buffer.replace(/\r\n/g, "\n").split("\n\n");
  const rest = parts.pop()!;
  return {
    rest,
    frames: parts
      .map((part) => {
        let event = "message",
          id = "";
        const data: string[] = [];
        for (const line of part.split("\n")) {
          if (line.startsWith("event:")) event = line.slice(6).trim();
          if (line.startsWith("id:")) id = line.slice(3).trim();
          if (line.startsWith("data:")) data.push(line.slice(5).trimStart());
        }
        return { event, id, data: data.join("\n") };
      })
      .filter((frame) => frame.data !== ""),
  };
}
