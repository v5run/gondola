import type { MenuItem, Reservation } from "./rush";

export type Channel = "doordash" | "ubereats" | "dine_in" | "pickup";
export type Priority = "current" | "arrival" | "promise" | "slack";
export interface Line { item: string; quantity: number }
export interface IncomingOrder { order_id: string; channel: Channel; received_minute: number; requested_ready_minute: number; latest_ready_minute?: number | null; items: Line[]; commitment: "request" | "confirmed" }
export interface Order extends IncomingOrder { key: string; status: string; decision: string | null; promise: number | null; predicted_ready: number | null; at_risk: boolean; response_deadline: number; reason: string; tasks: { id: string; station: string; start: number | null; end: number | null }[] }
export interface Decision { order_key: string; decision: string; promise: number | null; predicted_ready: number | null; reason: string }
export interface OrderReceipt { receipt_id: string; minute: number; action: string; status: string; decision_mode: string; decisions?: Decision[]; strategy?: Priority; external_verified: boolean }
export interface OrderSession { id: string; revision: number; minute: number; source_mode: string; external_writes: boolean; orders: Order[]; plan: Reservation[]; stations: { id: string; load: number; speed: number; blocked_until: number }[]; shared_cook_utilization: number; policy: { cooks: number; reserve_minutes: number; max_lead_minutes: number; response_minutes: number; default_priority: Priority }; stock: Record<string, number>; counts: Record<string, number>; at_risk: number; stock_shortfalls: Record<string, number>; receipts: OrderReceipt[] }
export interface AdmissionPlan { plan_id: string; revision: number; strategy: Priority; label: string; allowed: boolean; worsened_orders: string[]; reason: string; accepted_now: number; accepted_later: number; declined: number; existing_late_minutes: number; remaining_flow_minutes: number; next_work: Reservation[]; actions: Decision[]; plan: Reservation[] }
export interface PlanSet { revision: number; plans: AdmissionPlan[]; recommended: Priority }
export interface OrderConfig { menu: Record<string, MenuItem>; channels: Channel[]; agent_count: number; agent_configured: boolean; external_writes: boolean }
export interface OrderJob { id: string; kind: string; status: string; events: { kind: string; tool?: string; result?: { status?: string } }[]; error?: string; result?: { receipt: OrderReceipt; model: string; local_receipt_verified: boolean } }

export class OrderApiError extends Error { constructor(message: string, public status: number) { super(message); } }
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/${path}`, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new OrderApiError(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || "Request failed"), response.status);
  return data;
}
const sessionPath = (id: string) => `demand/sessions/${encodeURIComponent(id)}`;
const command = (session: OrderSession) => ({ revision: session.revision, event_id: crypto.randomUUID() });
export const orderApi = {
  config: () => request<OrderConfig>("demand/config"),
  sessions: () => request<{ id: string; created: string }[]>("demand/sessions"),
  create: (cooks: number, demo: boolean) => request<OrderSession>("demand/sessions", { policy: { cooks }, demo_burst: demo }),
  get: (id: string) => request<OrderSession>(sessionPath(id)),
  plans: (id: string) => request<PlanSet>(`${sessionPath(id)}/plans`),
  intake: (s: OrderSession, orders: IncomingOrder[]) => request<{ session: OrderSession }>(`${sessionPath(s.id)}/orders`, { ...command(s), orders }),
  apply: (s: OrderSession, plan: AdmissionPlan) => request<{ session: OrderSession; receipt: OrderReceipt }>(`${sessionPath(s.id)}/apply`, { ...command(s), strategy: plan.strategy, plan_id: plan.plan_id }),
  advance: (s: OrderSession, minute: number) => request<{ session: OrderSession }>(`${sessionPath(s.id)}/advance`, { ...command(s), minute }),
  capacity: (s: OrderSession, speed: number) => request<{ session: OrderSession }>(`${sessionPath(s.id)}/capacity`, { ...command(s), station: "fryer", speed }),
  agent: (s: OrderSession) => request<{ id: string }>(`${sessionPath(s.id)}/agent`, { revision: s.revision }),
  job: (id: string) => request<OrderJob>(`rush/jobs/${encodeURIComponent(id)}`),
};
