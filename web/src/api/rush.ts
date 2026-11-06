export interface OfferPolicy { name: string; load_weight: number; minimum_margin_cents: number; reserve_minutes: number; discount_cents: number; max_station_load: number }
export interface RushRequest { scenario: string; seed: number; incident: string; incident_at: number; budget_cents: number; cooks: number; forecast_pressure: number; policy: OfferPolicy }
export interface MenuItem { name: string; station: string; minutes: number; price: number; cost: number; stock: number }
export interface RushConfig { menu: Record<string, MenuItem>; modes: Record<string, string>; agent_configured: boolean; model: string | null; forecast: { p10: number; p50: number; p90: number; date: string; source: string } | null; scenarios: { id: string; name: string; description: string }[] }
export interface Ticket { id: string; item: string; channel: string; created: number; promise: number; eta: number | null; origin: string; ready: number | null; predicted_ready: number | null; state: string }
export interface Reservation { task_id: string; order_id: string; station: string; start: number; end: number; item?: string; frozen?: boolean }
export interface Offer { item: string; discount_cents: number; until: number; source: string }
export interface Receipt { status: string; action?: string; source?: string; minute: number; item?: string; discount_cents?: number; receipt_id?: string; evidence?: OfferCheck }
export interface OfferCheck { item: string; name: string; allowed: boolean; reason: string; station: string; station_load: number; predicted_ready_minute: number; promise_minute: number; contribution_cents: number }
export interface Learning { minute: number; item: string; estimated_work: number; observed_work: number; updated_estimate: number }
export interface Frame { minute: number; clock: string; stations: { id: string; load: number; speed: number; active: string[]; blocked: boolean }[]; orders: Ticket[]; plan: Reservation[]; offer: Offer | null; offer_checks: OfferCheck[]; spent_cents: number; events: { minute: number; kind: string; text: string }[]; actions: Receipt[]; learning: Learning[]; stock: Record<string, number> }
export interface Metrics { accepted: number; completed: number; unresolved: number; on_time: number; late: number; existing_orders: number; existing_on_time: number; visitor_orders: number; contribution_cents: number; promo_spend_cents: number; courier_wait_minutes: number; avg_courier_wait_minutes: number; worst_pickup_wait_minutes: number; avg_wait_minutes: number; food_hold_minutes: number; worst_lateness_minutes: number; late_minutes: number; service_score: number; schedule_changes: number; by_channel: Record<string, { accepted: number; late: number }> }
export interface RushRun { mode: string; label: string; metrics: Metrics; frames: Frame[]; actual_tasks: Reservation[]; actions: Receipt[]; learning: Learning[]; policy: OfferPolicy; menu: Record<string, MenuItem> }
export interface Comparison { id?: string; request: RushRequest; runs: Record<string, RushRun>; source_mode: string; assumptions: Record<string, unknown> }
export interface Evaluation { mean_score: number; mean_contribution_cents: number; mean_existing_on_time: number; checks_pass: boolean; policy: OfferPolicy; cases: { scenario: string; seed: number; metrics: Metrics }[] }
export interface ModelEvent { kind: string; tool?: string; text?: string; status?: string; args?: Record<string, unknown>; result?: any }
export interface ModelJob { id: string; status: string; kind: string; created: string; events: ModelEvent[]; error?: string; result?: { model: string; trace?: { tool: string; args: any; result: any }[]; tool_calls: any[]; usage: any[]; receipt?: Receipt; comparison?: Comparison; trials?: Evaluation[]; qualification?: { qualified: boolean; explanation: string; preserves_each_case: boolean; candidate: Evaluation; default: Evaluation; conventional_search: Evaluation; selected_policy: OfferPolicy; selection: string } } }

export const defaultPolicy: OfferPolicy = { name: "Protect the rush", load_weight: 7, minimum_margin_cents: 350, reserve_minutes: 3, discount_cents: 100, max_station_load: 0.9 };
export const defaultRequest: RushRequest = { scenario: "rush", seed: 7, incident: "fryer_slowdown", incident_at: 12, budget_cents: 1200, cooks: 3, forecast_pressure: 1, policy: defaultPolicy };

// No mock fallback: a failed backend/model must remain visible on this screen.
async function request<T>(path: string, body?: unknown): Promise<T> {
  const response = await fetch(`/api/rush/${path}`, body === undefined ? undefined : { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const data = await response.json();
  if (!response.ok) throw new Error(typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail || data.error || "Request failed"));
  return data;
}
export const rushApi = {
  config: () => request<RushConfig>("config"),
  compare: (body: RushRequest) => request<Comparison>("compare", body),
  agent: (body: RushRequest & { minute: number }) => request<{ id: string }>("agent", body),
  lab: () => request<{ id: string }>("lab", { objective: "Develop and test a policy that improves modeled contribution while preserving accepted-order service. Compare actual test feedback and submit a tested policy." }),
  job: (id: string) => request<ModelJob>(`jobs/${encodeURIComponent(id)}`),
  history: () => request<{ id: string; kind: string; status: string; created: string }[]>("history"),
};
