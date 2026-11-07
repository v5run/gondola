/** Typed client for the Past / Present / Future / Review endpoints (docs/architecture/TRI_WORKFLOW_API.md).
 *  In mock mode the same paths are answered by api/mockTri.ts through api/mock.ts. */
import { clearCache, req } from "./client";

export type TriChannel = "doordash" | "ubereats" | "grubhub" | "pickup" | "dine_in";
export const TRI_CHANNELS: TriChannel[] = ["doordash", "ubereats", "grubhub", "pickup", "dine_in"];
export const DELIVERY_APPS = ["doordash", "ubereats", "grubhub"] as const;

/* ---------------- Past ---------------- */
export interface LedgerEvent { id: number; date: string; ts: string; type: string; source: string; key?: string | null; payload: Record<string, any> }
export interface PastSummary {
  date: string; cutoff: string | null; processed: number;
  by_channel: Record<string, { orders: number; sales: number }>;
  promises_met: number; promises_total: number; avg_wait_min: number | null; worst_wait_min: number | null; avg_hold_min: number | null;
  cancels: number; refunds: number; actions_count: number;
}

/* ---------------- Present ---------------- */
export type QueueStatus = "queued" | "cooking" | "packing" | "ready";
export const FACTOR_KEYS = ["courier", "distance", "hold", "weather", "batch", "fairness", "in_store"] as const;
export type FactorKey = (typeof FACTOR_KEYS)[number];
/** A factor is its effect on the order's priority in minutes (+ = more slack, can wait; − = sooner). Some backends send {min, note}. */
export type FactorVal = number | { min?: number; value?: number; note?: string } | null;
export interface QueueRow {
  rank: number; order_id: string; channel: TriChannel | string; items: string[]; fulfillment: "delivery" | "pickup" | "dine_in" | string;
  promise: string | null; courier_eta: string | null; courier_distance_km: number | null; customer_distance_km: number | null;
  due: string | null; latest_start: string | null; slack_min: number | null; station: string | null; status: QueueStatus | string;
  courier_arrived?: boolean; customer_present?: boolean; quoted_extra_min?: number; planned_ready?: string | null; predicted_late_min?: number;
  factors: Partial<Record<FactorKey, FactorVal>>; reason: string;
}
export interface StationTask { order_id: string; item: string; start: string; end: string; frozen?: boolean; channel?: string }
export interface Station { key: string; name: string; speed: number; busy_until: string | null; tasks: StationTask[] }
export type AppState = "open" | "quoted" | "paused_items" | "busy";
export interface ChannelState { state: AppState | string; quoted_extra_min?: number; paused_items?: string[] }
export interface Action {
  ts?: string; time?: string; minute?: number; from?: string; action: string; channel?: string | null; item?: string | null; value?: number | string | null;
  ladder_level?: string | number | null; headroom_pct?: number | null; reason?: string; by?: string; receipt_id?: string;
}
/** promises_met is a share 0–1 after normalisation. */
export interface CompareSide { promises_met: number | null; avg_wait: number | null; worst_wait: number | null; hold: number | null; late?: number | null; declined?: number | null }
export interface Ladder { level: string | number; name: string; since: string | null; next_threshold: number | Record<string, number> | null; pending?: string | null }
export interface PresentState {
  date: string; now: string; phase: string; headroom_pct: number; ladder: Ladder; queue: QueueRow[]; stations: Station[];
  headroom?: { pct: number; binding?: string; forecast_orders?: number; window_min?: number } | null;
  incidents?: { kind?: string; station?: string; text?: string; start?: number; end?: number }[];
  channels: Record<string, ChannelState>; actions: Action[]; playback_actions?: Action[]; weather: { rain: boolean; temp_c: number | null; source: string } | null;
  compare?: { fifo: CompareSide; gondola: CompareSide } | null;
}
export interface Compare { fifo: CompareSide; gondola: CompareSide; orders: number }
export interface Simulation { headroom_pct_before: number; headroom_pct_after: number; late_orders_before: number; late_orders_after: number; late_minutes_before?: number; late_minutes_after?: number; lost_orders?: number; notes: string[] | string }
export interface AgentRun { decision: string; actions: Action[]; receipt: Record<string, any> | string | null }
export interface PresentSettings {
  ladder: { promote_above: number; quote_below: number; pause_below: number; busy_below: number; hysteresis_min: number; [k: string]: number };
  weights: Record<string, number>; max_wait_min: number; [k: string]: unknown;
}

/* ---------------- Future ---------------- */
export interface Range3 { p10: number; p50: number; p90: number }
export interface FutureBin { time: string; channel: string; p10: number; p50: number; p90: number; actual?: number | null }
/** effect_pct is a fraction (0.08 = +8%) after normalisation; the API sends percent. */
export interface FutureDriver { kind: string; label: string; time?: string | null; window?: string | null; effect_pct: number; channel_note?: string | null; why: string; estimate: boolean; evidence?: string[]; examples?: number }
export interface Adjustment { driver: string; pct: number; evidence: string | string[]; by: string }
export interface FutureToday {
  date: string; now: string; so_far: { orders: number; expected_by_now: number; vs_expected_pct: number | null };
  expected: Range3; rest: Range3; bins: FutureBin[]; drivers: FutureDriver[]; adjustments: Adjustment[];
}
export type PauseMap = Partial<Record<"doordash" | "ubereats" | "grubhub", string | null>>;
export interface DayCard { item: string; key?: string; unit?: string; target: number; prep: number; on_hand: number; pause_at: PauseMap; pause_if_busy: PauseMap; recount_at: number | string | null; batch?: number; buffer?: number; per_order?: number; warnings?: string[] }
export interface FutureDay {
  date: string; p10: number; p50: number; p90: number; rush: { start: string; end: string } | null; drivers: FutureDriver[]; weather_known: boolean; cards: DayCard[]; curve?: { time: string; orders: number }[];
}
export interface LimitedItem { key: string; name: string; unit: string; believed_left: number; projected_runout: string | null; pause_at: PauseMap; recount_at: number | string | null; made?: number; prep?: number; recount_time?: string | null }
export interface Outlook {
  status: "agent" | "fallback"; active: boolean; reason: string; target_date: string; run_id?: string; issue_minute?: number;
  scenario?: { anchor: string; event_id: string; assumed_pct: number; total_p50: number; uncertainty: string; warning: string };
  ml_reference?: { total: Range3; agent_inspected?: boolean }; weather?: { source: string; rain: boolean; snow: boolean; temp_high_c: number | null };
  events?: { id: string; title: string; start: string; distance_km: number; status: string; source: string }[];
  analogs?: { date: string; orders: number }[]; tools_called?: string[]; interpretation?: string[]; model?: string; source_mode?: string;
}

/* ---------------- Review ---------------- */
export type Severity = "critical" | "high" | "warn" | "medium" | "info" | "low" | string;
export interface ExceptionItem { id: string; ts: string; kind: string; severity: Severity; title: string; decision: "alert" | "present" | "note" | string; note: string; resolved: boolean | string | null; by?: string; evidence?: unknown; alert?: unknown }
export interface Evidenced { text: string; evidence?: string | string[] | null }
export interface ActionItem { id: string; text: string; owner: string | null; created?: string; check_on: string | null; measure: string | Record<string, unknown> | null; status: string; outcome?: string | { checked_on?: string; note?: string | null; by?: string; [k: string]: unknown } | null; progress?: unknown }
export interface DayReview {
  date: string; status: string; well: Evidenced[]; wrong: Evidenced[]; causes: Evidenced[]; actions: ActionItem[];
  kb_changes: { id: string; op: string; statement: string; status: string }[]; digest_id: string | null;
}
export interface KbItem {
  id: string; kind: string; scope: Record<string, any>; statement: string; effect?: Record<string, any> | null; evidence: string[]; n: number;
  confidence: number; status: string; created: string; last_confirmed: string; source: string; needs_approval?: boolean; replaced_by?: string | null;
}
export interface Digest { id: string; kind: "shift" | "day" | "week" | "month" | string; period: string; summary: string | string[]; numbers: Record<string, any> | null;
  well?: unknown; wrong?: unknown; wrong_themes?: unknown; bullets?: string[] }
export interface ContextPayload { agent: string; date?: string; tokens: number; budget?: number; budget_tokens?: number; payload?: any; dropped?: unknown[]; [k: string]: any }

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });
const put = (body: unknown): RequestInit => ({ method: "PUT", body: JSON.stringify(body) });
const q = (o: Record<string, string | number | null | undefined>) => {
  const s = Object.entries(o).filter(([, v]) => v !== undefined && v !== null && v !== "").map(([k, v]) => `${k}=${encodeURIComponent(String(v))}`).join("&");
  return s ? `?${s}` : "";
};

/* ---------------- normalisation: accept the contract and what the backends actually send ---------------- */
/** Ladder level key from "pause" / "Pause slow items" / -2 etc. */
export const levelKey = (l: unknown): "promote" | "normal" | "quote" | "pause_items" | "busy" => {
  if (typeof l === "number") return l >= 1 ? "promote" : l === 0 ? "normal" : l === -1 ? "quote" : l === -2 ? "pause_items" : "busy";
  const s = String(l ?? "").toLowerCase();
  return s.startsWith("pause") ? "pause_items" : s.startsWith("busy") ? "busy" : s.startsWith("quot") ? "quote" : s.startsWith("promo") ? "promote" : "normal";
};
export function normSide(x: any): CompareSide {
  if (!x) return { promises_met: null, avg_wait: null, worst_wait: null, hold: null };
  const pm = x.promises_met_pct !== undefined && x.promises_met_pct !== null ? x.promises_met_pct / 100
    : x.promises_total ? x.promises_met / x.promises_total : typeof x.promises_met === "number" ? (x.promises_met > 1 ? x.promises_met / 100 : x.promises_met) : null;
  return { promises_met: pm, avg_wait: x.avg_wait ?? x.avg_wait_min ?? null, worst_wait: x.worst_wait ?? x.worst_wait_min ?? null,
    hold: x.avg_hold ?? x.avg_hold_min ?? x.hold ?? null, late: x.late_orders ?? x.late ?? null, declined: x.declined ?? null };
}
export function normAction(a: Action, date: string): Action {
  const ts = a.ts || (a.time ? `${date}T${a.time.length === 5 ? `${a.time}:00` : a.time}` : undefined);
  return { ...a, ts };
}
export function normState(s: PresentState): PresentState {
  const d = s.date;
  const actions = (s.actions || []).map((a) => normAction(a, d)).sort((a, b) => String(b.ts || "").localeCompare(String(a.ts || "")));
  return {
    ...s, now: s.now || "00:00", headroom_pct: s.headroom_pct ?? s.headroom?.pct ?? 0, actions,
    ladder: s.ladder || { level: "normal", name: "Normal", since: null, next_threshold: null },
    queue: s.queue || [], stations: s.stations || [], channels: s.channels || {},
    compare: s.compare ? { fifo: normSide(s.compare.fifo), gondola: normSide(s.compare.gondola) } : null,
  };
}

const hhmm = (w: any): string | null => (!w ? null : typeof w === "string" ? w : w.start && w.end ? `${w.start}–${w.end}` : null);
/** Drivers: percent → fraction, window objects → "HH:MM–HH:MM". */
export const normDriver = (d: any): FutureDriver => ({ ...d, effect_pct: (Number(d.effect_pct) || 0) / 100, window: hhmm(d.window), estimate: !!d.estimate });
export function normToday(t: any): FutureToday {
  const bins: FutureBin[] = (t.bins || []).map((b: any) => {
    const p50 = b.p50 ?? b.forecast_p50 ?? 0;
    return { time: b.time, channel: b.channel, p50, p10: b.p10 ?? p50, p90: b.p90 ?? p50, actual: b.actual ?? null };
  });
  const sf = t.so_far || { orders: 0, expected_by_now: 0, vs_expected_pct: null };
  return { ...t, bins, drivers: (t.drivers || []).map(normDriver), adjustments: t.adjustments || [],
    so_far: { ...sf, vs_expected_pct: sf.vs_expected_pct === null || sf.vs_expected_pct === undefined ? null : sf.vs_expected_pct / 100 } };
}
const unitName = (u: string) => ({ portion: "portions", each: "", piece: "pieces", litre: "litres", liter: "litres" } as Record<string, string>)[u] || u;
export const normItem = (i: any): LimitedItem => ({ ...i, unit: unitName(i.unit || ""), made: i.made ?? i.prep });
export const normDay = (d: any): FutureDay => ({ ...d, drivers: (d.drivers || []).map(normDriver), cards: (d.cards || []).map((c: any) => ({ ...c, unit: unitName(c.unit || "") })) });

export const tri = {
  past: {
    summary: (date: string, at?: string) => req<PastSummary>(`/past/summary${q({ date, at })}`),
    ledger: (date: string, opts: { at?: string; types?: string[]; limit?: number; before_id?: number | null } = {}) =>
      req<{ events: LedgerEvent[]; next_before_id: number | null }>(`/past/ledger${q({ date, at: opts.at, types: opts.types?.join(","), limit: opts.limit ?? 200, before_id: opts.before_id })}`),
  },
  present: {
    state: (date: string, at?: string, after?: string, compare?: boolean) =>
      req<PresentState>(`/present/state${q({ date, at, after, compare: compare ? "true" : undefined })}`).then(normState),
    compare: (date: string) => req<any>(`/present/compare${q({ date })}`).then((c): Compare => ({ fifo: normSide(c.fifo), gondola: normSide(c.gondola), orders: c.orders ?? 0 })),
    simulate: (date: string, action: Record<string, unknown>) => req<Simulation>("/present/simulate", post({ date, action })),
    agent: (date: string) => req<AgentRun>("/present/agent", post({ date })).then((r) => ({ ...r, actions: (r.actions || []).map((a) => normAction(a, date)) })),
    settings: () => req<PresentSettings>("/present/settings"),
    saveSettings: (s: PresentSettings) => req<PresentSettings>("/present/settings", put(s)),
  },
  future: {
    today: (date: string, at?: string) => req<any>(`/future/today${q({ date, at })}`).then(normToday),
    days: (start: string, n = 1) => req<any[]>(`/future/days${q({ start, n })}`).then((l) => l.map(normDay)),
    items: (date: string, at?: string) => req<{ items: any[] }>(`/future/items${q({ date, at })}`).then((r) => ({ items: (r.items || []).map(normItem) })),
    outlook: (date: string) => req<Outlook>(`/future/outlook${q({ date })}`),
    runOutlook: (date: string) => req<Outlook>("/future/outlook", post({ date })),
  },
  review: {
    exceptions: (date: string) => req<ExceptionItem[]>(`/review/exceptions${q({ date })}`),
    resolve: (id: string, date?: string) => req<{ ok: boolean }>(`/review/exceptions/${encodeURIComponent(id)}/resolve`, post(date ? { date } : {})),
    scan: (date: string) => req<ExceptionItem[] | { new?: ExceptionItem[]; exceptions?: ExceptionItem[] }>("/review/scan", post({ date })),
    day: (date: string) => req<DayReview>(`/review/day/${date}`),
    run: (date: string) => { clearCache(); return req<DayReview | { ok: boolean }>("/review/run", post({ date })); },
    kb: (status?: string, kind?: string) => req<KbItem[]>(`/review/kb${q({ status, kind })}`),
    approve: (id: string) => req<{ ok: boolean; item: KbItem }>(`/review/kb/${encodeURIComponent(id)}/approve`, post({})),
    retire: (id: string) => req<{ ok: boolean; item: KbItem }>(`/review/kb/${encodeURIComponent(id)}/retire`, post({})),
    actions: (status?: string) => req<ActionItem[]>(`/review/actions${q({ status })}`),
    setAction: (id: string, status: "done" | "not_working" | "open", note?: string) => req<{ ok: boolean }>(`/review/actions/${encodeURIComponent(id)}/status`, post({ status, note })),
    digests: (kind: string, limit = 30) => req<Digest[]>(`/review/digests${q({ kind, limit })}`),
    context: (agent: string, date: string) => req<ContextPayload>(`/review/context${q({ agent, date })}`),
  },
};

/** Factor value in minutes, whichever shape the backend sent. */
export const factorMin = (v: FactorVal | undefined): number => {
  if (v === null || v === undefined) return 0;
  if (typeof v === "number") return v;
  return Number(v.min ?? v.value ?? 0) || 0;
};
export const factorNote = (v: FactorVal | undefined): string | null => (v && typeof v === "object" ? v.note ?? null : null);
/** Normalise POST /review/scan, which may return a list or an object. */
export const scanList = (r: Awaited<ReturnType<typeof tri.review.scan>>): ExceptionItem[] =>
  Array.isArray(r) ? r : r.new || r.exceptions || [];
/** The text of an action item's outcome, whichever shape it came in. */
export const outcomeText = (o: ActionItem["outcome"]): string | null => (!o ? null : typeof o === "string" ? o : o.note ? String(o.note) : o.checked_on ? `Checked ${o.checked_on}` : null);
export const isResolved = (x: ExceptionItem) => !!x.resolved;
export const sevRank = (s: Severity) => (/crit|high|urgent/.test(s) ? 0 : /warn|med/.test(s) ? 1 : 2);
