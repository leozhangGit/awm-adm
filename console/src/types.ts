export type Json =
  | null
  | boolean
  | number
  | string
  | Json[]
  | { [key: string]: Json };
export type Spec = {
  ref?: string;
  kind?: string;
  min?: number;
  max?: number;
  values?: string[];
  fields?: Record<string, Spec>;
  variants?: Record<string, Spec>;
  element?: Spec;
  length?: number;
  base?: Spec;
};
export type Declaration = {
  kind: string;
  type?: Spec;
  params?: Record<string, Spec>;
  returns?: Spec;
  state?: Spec;
  [key: string]: unknown;
};
export type Context = {
  adm_id?: string;
  instance_id?: string;
  theory_root?: string;
  theory_version?: string;
  support_root: string;
  policy_epoch: number;
  mode?: string;
};
export type Adm = Context & {
  id: string;
  name: string;
  mode: "forward" | "backward";
  status: string;
  archived?: boolean;
  revision_id?: string;
};
export type Model = {
  revision_id: string;
  context: Context;
  declarations: Record<string, Declaration>;
  artifacts: { digest: string; role: string; value: Json }[];
};
export type Result = {
  result_id: string;
  binding: {
    context: Context;
    request_id: string;
    attempt_id: string;
    selection: { kind: string; actions: string[] | null };
    resolved_actions: string[];
  };
  value: Record<string, Json>;
  claims: string[];
  lean_kernel: string;
  exhaustive_finite: string;
  empirical_fidelity: string;
};
export type RequestItem = {
  adm_id: string;
  request_id: string;
  status: string;
  attempt_id: string | null;
  result_id?: string | null;
  pinned_context: Context;
};
export type RequestView = RequestItem & {
  result: Result | null;
  error: { message: string; code: string } | null;
  query: Json;
  revision_id: string;
  current_context: Context;
  attempts: {
    id: string;
    status: string;
    started: number;
    ended: number | null;
  }[];
};
export type Operation = {
  operation_id: string;
  kind: string;
  adm_id: string | null;
  status: string;
  result?: { adm_id?: string; snapshot?: Json };
  error?: { message: string };
};
export type Page<T> = { items: T[]; next_cursor: number | null };
export type System = {
  product: string;
  version: string;
  operational: boolean;
  available: Record<string, boolean>;
};
export type Session = { id: string; csrf: string };
export type Limits = {
  max_work: number;
  max_duration_ms: number;
  max_states: number;
  max_search_bytes: number;
};
export const active = (status: string) =>
  ["received", "evaluating", "waiting_for_learning"].includes(status);
export const short = (value?: string | null) =>
  value ? value.replace("sha256:", "").slice(0, 10) : "—";
export const pretty = (value: unknown) => JSON.stringify(value, null, 2);
