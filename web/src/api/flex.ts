import type { ModelEvent } from "./rush";

export interface FlexTask { task_id: string; order_id: string; station: string; start: number; end: number; item: string; channel?: string }
export interface FlexOption { id: string; kind: "regular" | "flexible"; pickup_minute: number; pickup_clock: string; tasks: FlexTask[]; cook_minutes: number; holding_minutes: number; discount_cents: number; price_cents: number; released_cook_minutes: number; reason: string; score: number }
export interface FlexCart { cart_id: string; item: string; latest_pickup_minute: number; minimum_saving_cents: number }
export interface FlexConfig { scenario: string; seed: number; cooks: number; budget_cents: number; max_discount_cents: number; quote_ttl_seconds: number }
export interface FlexQuote { id: string; cart: FlexCart; revision: number; status: string; source: string; expires_at: number; created_at: number; options: FlexOption[]; no_deal_reason: string | null; contract: string; baseline_allocations: FlexTask[]; evidence: { protected_existing_tasks: number; candidates_checked: number }; receipt?: FlexReceipt }
export interface FlexReceipt { id: string; cart_id: string; item: string; option: FlexOption; regular_option: FlexOption; quote_id?: string; accepted_at: number; consent: string; source: string; status: string; payment_mode: string; replayed?: boolean; comparison?: { allocations: FlexTask[]; regular: FlexOption; selected: FlexOption; peak_start: number; peak_end: number } }
export interface FlexSession { id: string; config: FlexConfig; revision: number; minute: number; clock: string; peak_end: number; spent_cents: number; menu: Record<string, { name: string; station: string; price: number; cost: number; available: number }>; base_plan: FlexTask[]; base_orders: { id: string; item: string; channel: string; promise: number; ready: number | null }[]; bookings: FlexReceipt[]; events: { kind: string; quote_id?: string; order_id?: string; source?: string }[]; pressure: { stations: Record<string, number>; shared_cooks: number; congested: boolean }; quote_summaries: { id: string; status: string; source: string; expires_at: number }[]; assumptions: Record<string, string> }
export interface FlexJob { id: string; status: string; events: ModelEvent[]; error?: string; result?: { quote: FlexQuote; session: FlexSession; agent_mode: string; model: string; tool_sequence: string[] } }
export class FlexError extends Error { constructor(message: string, public status: number) { super(message); } }
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/flex/${path}`, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new FlexError(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data.error), response.status);
  return data;
}
const at = (id: string) => `sessions/${encodeURIComponent(id)}`;
export const flexApi = {
  create: (body: FlexConfig) => request<FlexSession>("sessions", body),
  session: (id: string) => request<FlexSession>(at(id)),
  quote: (id: string, body: FlexCart) => request<FlexQuote>(`${at(id)}/quotes`, body),
  getQuote: (id: string, qid: string) => request<FlexQuote>(`${at(id)}/quotes/${encodeURIComponent(qid)}`),
  accept: (id: string, qid: string, option: string) => request<FlexReceipt>(`${at(id)}/quotes/${qid}/accept`, { option_id: option }),
  decline: (id: string, qid: string) => request<{ status: string }>(`${at(id)}/quotes/${qid}/decline`, {}),
  compete: (id: string, qid: string, option: string) => request<FlexReceipt>(`${at(id)}/quotes/${qid}/compete`, { option_id: option }),
  agent: (id: string, body: FlexCart) => request<{ id: string }>(`${at(id)}/agent`, body),
  job: async (id: string): Promise<FlexJob> => { const r = await fetch(`/api/rush/jobs/${encodeURIComponent(id)}`); const d = await r.json(); if (!r.ok) throw new Error(d.detail || "Could not load agent job"); return d; },
};
