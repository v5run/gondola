export type Channel = "in_store" | "doordash" | "ubereats" | "grubhub";
export type App = "doordash" | "ubereats" | "grubhub";

export interface Store {
  id: string; name: string; address: string; today: string; tomorrow: string; first_date: string; limited_items: string[];
}
export interface Integrations {
  twilio: { live: boolean }; sendgrid: { live: boolean }; llm: { live: boolean; model?: string };
  square: { live: boolean }; doordash: { live: boolean };
}
export interface Point { time: string; orders: number }
export interface Overview {
  date: string; closed?: boolean; not_open_yet?: boolean; opens?: string | null; as_of?: string | null;
  kpis: { net_sales: number; orders: number; avg_ticket: number; labour_pct: number; cancels: number; avoidable_cancels: number };
  vs_usual: Record<string, number | null>;
  context: { rain: boolean; events: string[] };
  curve_today: Point[]; curve_usual: Point[];
  channels: { key: string; today: number; usual: number; change?: number }[];
  last_close: { status: string; finished_at: string } | null;
}
export interface DailyMetric {
  date: string; orders: number; net_sales: number; avg_ticket: number; labour_pct: number; cancels: number;
  avoidable_cancels: number; rain: boolean; events: string;
}
export interface Forecast {
  date: string; p10: number; p50: number; p90: number;
  rush: { start: string; end: string; peak_per_15min: number };
  curve: Point[]; similar_days: { date: string; orders: number; why: string }[]; model: string;
}
export type StepStatus = "queued" | "running" | "done" | "failed" | "skipped";
export interface StepEvent { step: string; status: StepStatus; seconds?: number; message?: string }
export interface Finding { kind: string; title?: string; urgency?: string; impact_usd?: number | null; [k: string]: unknown }
export interface CardItem {
  item: string; target: number; on_hand: number; prep: number;
  pause_at: Record<App, string | null>; pause_if_busy: Record<App, string | null>; recount_at: number; warnings?: string[]; portions_per_order?: number;
}
export interface PayoutChannel {
  channel: string; orders: number; sales: number; expected: number; reported: number | null; difference: number | null;
  error_charges?: number; fresh?: boolean;
}
export interface Dispute { channel: string; order: string; amount: number; reason: string; days_left: number; items?: string[]; date?: string }
export interface CloseDetail {
  date: string; status: string; seconds: number;
  log: { step: string; status: string; seconds: number; error?: string }[];
  findings: Finding[]; alerts: { body?: string; status?: string; key?: string; ts?: string }[]; card: CardItem[];
  books: {
    cash: { expected?: number; counted?: number | null; difference?: number | null; status?: string };
    verified: { date: string; channels: PayoutChannel[] }[];
    estimate_today: PayoutChannel[];
  };
  disputes: Dispute[]; demand: { p10: number; p50: number; p90: number; rush: { start: string; end: string } };
  approved: boolean; portions_per_order?: number; sold_out?: { at: string; app_cancels: number; minutes_live: number; by_channel?: Record<string, number>; portions_missed?: number; prepped?: number; used?: number } | null;
}
export interface CloseSummary { date: string; status: string; seconds: number; findings_count: number; urgent_count: number }
export interface ReportItem { date: string; kind: "daily" | "monthly"; status: string; url: string }
export interface AskAnswer {
  text: string; clarify: boolean; calls: unknown[];
  chart?: { type: "line" | "bar"; x: string[]; series: { name: string; values: number[] }[] } | null; mode?: string;
}
export interface OutboxMsg { channel: "sms" | "email"; to?: string | string[] | null; direction?: "in" | "out"; body: string; subject?: string; attachment?: string; status?: string; ts: string; from?: string | null }

export interface GuardTick {
  t: string; believed_left: number; sold: Record<Channel, number>; available: Record<Channel, boolean>; cancels: number; held_back: number;
}
export interface GuardDone { cancels: number; held_back: number; status_quo_cancels: number }

/* ---------- V3 ---------- */
export type ByChannel = Record<Channel, number>;
export interface LiveOrder { t: string; id: string; channel: Channel; items: string[]; subtotal: number; status: string; chashu?: number; cancel_reason?: string | null; catchup?: boolean }
/** The store clock (GET /api/now): real time in America/New_York mapped onto the data. */
export interface NowInfo { today: string; now: string; tz: string; mapped: boolean; business_date?: string; open: string; close: string; phase: "before_open" | "open" | "closed"; cutoff: string | null }
export interface LiveTick { t: string; orders: number; placed?: number; net_sales: number; by_channel: ByChannel; by_channel_sales?: ByChannel; chashu_left: number; cancels: number }
export interface LiveEvent { t: string; kind: "sold_out" | "pause" | "rush_start" | "rush_end" | string; text: string; app?: string; chashu_left?: number; catchup?: boolean }
export interface IntradayBin { time: string; orders: number; by_channel: ByChannel; net_sales: number }
export interface Intraday { date: string; as_of?: string | null; bins: IntradayBin[]; usual: Point[] }
export interface ItemRow { item: string; sold: number; net_sales: number; share: number }
export interface RangeMetrics {
  start: string; end: string; days: number; net_sales: number; orders: number; avg_ticket: number; labour_pct: number;
  cancels: number; avoidable_cancels: number; by_channel: ByChannel; vs_prev_pct: { net_sales: number | null; orders: number | null };
  best_day: BestDay | string | null; worst_day: BestDay | string | null;
  prev?: { start: string; end: string; net_sales: number; orders: number }; by_channel_orders?: ByChannel;
}
export interface Driver { key: string; today: number; usual: number; change: number }
export interface ItemChange { item: string; today: number; usual: number; change: number }
export interface Explain {
  vs_usual?: { net_sales_pct: number | null; orders_pct: number | null; baseline_dates?: string[] };
  vs_similar?: { net_sales_pct: number | null; orders_pct?: number | null; dates?: string[] } | null;
  drivers?: { channel?: Driver[]; daypart?: Driver[] };
  context?: { rain?: boolean; snow?: boolean; temp_high_c?: number | null; events?: string[] };
  items_up?: ItemChange[]; items_down?: ItemChange[];
}
export interface DayDetail {
  date?: string; explain?: Explain | null;
  overview: Overview & { closed?: boolean };
  close: CloseDetail | null;
  report: { status: string; url_html: string; url_pdf: string } | null;
}
export interface ReportEntry {
  date: string; kind: "daily" | "monthly"; status: "stored" | "expired" | "rebuilt" | string;
  url?: string; url_html?: string; url_pdf?: string; headline?: string; net_sales?: number; orders?: number;
  vs_usual_pct?: number | null; urgent?: number; texted?: boolean; recoverable_usd?: number;
}
export interface BestDay { date: string; net_sales: number; orders?: number; rain?: boolean; events?: string[] }
