import type {
  DayDetail, Intraday, ItemRow, RangeMetrics, ReportEntry,
  AskAnswer, CardItem, CloseDetail, CloseSummary, DailyMetric, Forecast, Integrations, OutboxMsg, Overview, Store,
} from "./types";
import { mock } from "./mock";

type Handlers = Record<string, (data: any) => void>;

let mode: "live" | "mock" | null = import.meta.env.VITE_MOCK === "1" ? "mock" : null;
let probing: Promise<"live" | "mock"> | null = null;

export async function apiMode(): Promise<"live" | "mock"> {
  if (mode) return mode;
  if (!probing) {
    probing = fetch("/api/health", { signal: AbortSignal.timeout(2500) })
      .then((r) => (r.ok ? r.json() : Promise.reject()))
      .then((j) => (j && j.ok ? "live" : "mock"))
      .catch(() => "mock" as const)
      .then((m) => (mode = m as "live" | "mock"));
  }
  return probing;
}

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  if ((await apiMode()) === "mock") return mock.request(path, init) as Promise<T>;
  const r = await fetch(`/api${path}`, {
    ...init, headers: { "Content-Type": "application/json", ...(init?.headers || {}) },
  });
  if (!r.ok) {
    let detail = r.statusText;
    try { const j = await r.json(); detail = j.detail || j.error || detail; } catch { /* ignore */ }
    throw new Error(typeof detail === "string" ? detail : JSON.stringify(detail));
  }
  return r.json();
}

/** Server-sent events. Returns a function that stops the stream. */
export function stream(path: string, on: Handlers): () => void {
  let stop = () => {};
  let cancelled = false;
  apiMode().then((m) => {
    if (cancelled) return;
    if (m === "mock") { stop = mock.stream(path, on); return; }
    const es = new EventSource(`/api${path}`);
    for (const name of Object.keys(on)) {
      es.addEventListener(name, (e) => {
        try { on[name](JSON.parse((e as MessageEvent).data)); } catch { on[name]((e as MessageEvent).data); }
        if (name === "done") es.close();
      });
    }
    es.onerror = () => { if (es.readyState === EventSource.CLOSED) on.error?.({ message: "Connection closed" }); };
    stop = () => es.close();
  });
  return () => { cancelled = true; stop(); };
}

/** Short-lived cache for idempotent GETs, so hovering a chart can prefetch what a click will show. */
const cache = new Map<string, { at: number; p: Promise<unknown> }>();
function cached<T>(path: string, ttl = 60000): Promise<T> {
  const hit = cache.get(path);
  if (hit && Date.now() - hit.at < ttl) return hit.p as Promise<T>;
  const p = req<T>(path);
  cache.set(path, { at: Date.now(), p });
  p.catch(() => cache.delete(path));
  return p;
}
export const clearCache = () => cache.clear();

const post = (body: unknown): RequestInit => ({ method: "POST", body: JSON.stringify(body) });

export const api = {
  store: () => req<Store>("/store"),
  integrations: () => req<Integrations>("/integrations"),
  overview: (date?: string) => req<Overview>(`/overview${date ? `?date=${date}` : ""}`),
  metrics: (start: string, end: string) => req<DailyMetric[]>(`/metrics/daily?start=${start}&end=${end}`),
  forecast: (date?: string) => req<Forecast>(`/forecast${date ? `?date=${date}` : ""}`),
  startClose: (body: { date?: string; portion_counts?: Record<string, number>; force?: boolean }) =>
    { clearCache(); return req<{ run_id: string; date: string }>("/close", post(body)); },
  closes: () => req<CloseSummary[]>("/closes"),
  close: (date: string) => req<CloseDetail>(`/closes/${date}`),
  approve: (date: string, card?: CardItem[]) => { clearCache(); return req<{ approved: boolean; card: CardItem[] }>(`/closes/${date}/approve`, post({ card })); },
  reports: () => req<ReportEntry[]>("/reports"),
  ask: (question: string, today?: string) => req<AskAnswer>("/ask", post(today ? { question, today } : { question })),
  intraday: (date: string) => cached<Intraday>(`/metrics/intraday?date=${date}`),
  items: (start: string, end: string) => cached<ItemRow[]>(`/metrics/items?start=${start}&end=${end}`),
  range: (start: string, end: string) => cached<RangeMetrics>(`/metrics/range?start=${start}&end=${end}`),
  day: (date: string) => cached<DayDetail>(`/day/${date}`, 20000),
  /** Fetch a report (rebuilding it server-side if expired); resolves when the HTML is ready. */
  rebuild: async (r: ReportEntry): Promise<void> => {
    if ((await apiMode()) === "mock") return mock.rebuild(r.date);
    const url = reportPaths(r).pdf;
    const res = await fetch(url);
    if (!res.ok) throw new Error(`Rebuild failed (${res.status})`);
    await res.arrayBuffer();
  },
  outbox: () => req<OutboxMsg[]>("/outbox"),
  smsInbound: async (body: string): Promise<string> => {
    if ((await apiMode()) === "mock") return mock.sms(body);
    const form = new URLSearchParams({ From: "+14125550142", Body: body });
    const r = await fetch("/api/sms/inbound", { method: "POST", body: form });
    const xml = await r.text();
    const m = xml.match(/<Message>([\s\S]*?)<\/Message>/);
    return m ? m[1].replace(/&amp;/g, "&").replace(/&lt;/g, "<").replace(/&gt;/g, ">").replace(/&quot;/g, '"').replace(/&#39;/g, "'") : xml;
  },
  guardReplay: (body: { date?: string; speed?: number; count_error?: number; recount?: boolean; start_time?: string }) =>
    req<{ run_id: string }>("/guard/replay", post(body)),
  guardRecount: (runId: string, count: number) => req<{ ok: boolean }>(`/guard/${runId}/recount`, post({ count })),
  reportUrls: async (date: string) => ((await apiMode()) === "mock"
    ? { view: mock.reportUrl(date), pdf: mock.reportUrl(date) }
    : { view: `/api/reports/${date}.html`, pdf: `/api/reports/${date}.pdf` }),
};

export function reportPaths(r: ReportEntry): { html: string; pdf: string } {
  if (mode === "mock") return { html: mock.reportUrl(r.date), pdf: mock.reportUrl(r.date) };
  const base = r.kind === "monthly" ? `/api/reports/monthly/${r.date}` : `/api/reports/${r.date}`;
  return { html: r.url_html || `${base}.html`, pdf: r.url_pdf || (r.url && r.url.endsWith(".pdf") ? r.url : `${base}.pdf`) };
}
