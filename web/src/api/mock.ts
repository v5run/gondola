/** Mock API used when the backend isn't running (or VITE_MOCK=1). Data comes from fixtures.json, which is
 *  generated from the real demo year by web/scripts/make_fixtures.py, so the numbers match the backend. */
import fx from "./fixtures.json";
import type { CardItem, Channel, CloseDetail, OutboxMsg } from "./types";

type Handlers = Record<string, (data: any) => void>;
const wait = (ms: number) => new Promise((r) => setTimeout(r, ms));
const clone = <T,>(x: T): T => JSON.parse(JSON.stringify(x));

const state = {
  close: clone(fx.close) as unknown as CloseDetail,
  closed: true,
  outbox: clone(fx.outbox) as unknown as OutboxMsg[],
  runs: new Map<string, { recount?: number; speed?: number }>(),
  rebuilt: new Set<string>(),
};

/* ---------- V3 sample data, derived from the real demo year in fixtures.json ---------- */
const CHS = ["in_store", "doordash", "ubereats", "grubhub"] as const;
const SHARE = (() => { const t = fx.overview.channels.reduce((a, c) => a + c.today, 0); return Object.fromEntries(fx.overview.channels.map((c) => [c.key, c.today / t])) as Record<string, number>; })();
const MENU: [string, number, number][] = [["Tonkotsu", 19.25, 0.26], ["Spicy Miso", 19.25, 0.17], ["Shoyu", 18.15, 0.12], ["Tantanmen", 19.8, 0.1], ["Chashu Don", 15.4, 0.09],
  ["Chashu Bao", 9.35, 0.08], ["Gyoza", 8.8, 0.08], ["Karaage", 10.45, 0.05], ["Edamame", 6.05, 0.03], ["Sapporo", 7.0, 0.02]];
let seed = 7;
const rnd = () => { seed = (seed * 16807) % 2147483647; return (seed - 1) / 2147483646; };
const metricOf = (d: string) => fx.metrics.find((m) => m.date === d);
const shapeFor = (d: string) => { const m = metricOf(d); const k = m ? m.orders / fx.overview.kpis.orders : 0; return fx.overview.curve_today.map((p) => ({ time: p.time, orders: Math.round(p.orders * k * 10) / 10 })); };
function overviewFor(d: string) {
  if (d === fx.store.today) return { ...fx.overview, last_close: state.closed ? fx.overview.last_close : null };
  const m = metricOf(d);
  if (!m || !m.orders) return { date: d, closed: true, kpis: null, vs_usual: null, context: { rain: false, events: ["Closed"] }, curve_today: [], curve_usual: [], channels: [], last_close: null };
  const same = fx.metrics.filter((x) => x.date < d && new Date(`${x.date}T12:00:00`).getDay() === new Date(`${d}T12:00:00`).getDay()).slice(-4);
  const u = same.length ? same.reduce((a, x) => a + x.net_sales, 0) / same.length : m.net_sales;
  const uo = same.length ? same.reduce((a, x) => a + x.orders, 0) / same.length : m.orders;
  return { date: d, kpis: { net_sales: m.net_sales, orders: m.orders, avg_ticket: m.avg_ticket, labour_pct: m.labour_pct, cancels: m.cancels, avoidable_cancels: m.avoidable_cancels },
    vs_usual: { net_sales_pct: m.net_sales / u - 1, orders_pct: m.orders / uo - 1, avg_ticket_pct: m.avg_ticket / (u / uo) - 1, labour_pct_pct: 0 },
    context: { rain: m.rain, events: Array.isArray(m.events) ? m.events : [] }, curve_today: shapeFor(d),
    curve_usual: fx.overview.curve_usual.map((p) => ({ ...p, orders: (p.orders * uo) / fx.overview.kpis.orders })),
    channels: CHS.map((c) => ({ key: c, today: m.net_sales * SHARE[c], usual: u * SHARE[c] })), last_close: null };
}
function intraday(d: string) {
  const o = overviewFor(d) as { curve_today: { time: string; orders: number }[]; curve_usual: { time: string; orders: number }[]; kpis: { avg_ticket: number } | null };
  return { date: d, usual: o.curve_usual, bins: o.curve_today.map((p) => ({ time: p.time, orders: p.orders, net_sales: p.orders * (o.kpis?.avg_ticket || 30),
    by_channel: Object.fromEntries(CHS.map((c) => [c, Math.round(p.orders * SHARE[c] * 10) / 10])) })) };
}
function range(a: string, b: string) {
  const r = fx.metrics.filter((m) => m.date >= a && m.date <= b && m.orders > 0);
  const n = Math.round((new Date(`${b}T12:00:00`).getTime() - new Date(`${a}T12:00:00`).getTime()) / 864e5) + 1;
  const pa = new Date(`${a}T12:00:00`); pa.setDate(pa.getDate() - n);
  const pb = new Date(`${a}T12:00:00`); pb.setDate(pb.getDate() - 1);
  const prev = fx.metrics.filter((m) => m.date >= pa.toISOString().slice(0, 10) && m.date <= pb.toISOString().slice(0, 10));
  const sum = (x: typeof r, k: "net_sales" | "orders" | "cancels" | "avoidable_cancels") => x.reduce((s, m) => s + m[k], 0);
  const ns = sum(r, "net_sales"), or = sum(r, "orders");
  const sorted = [...r].sort((x, y) => y.net_sales - x.net_sales);
  return { start: a, end: b, days: n, net_sales: ns, orders: or, avg_ticket: or ? ns / or : 0,
    labour_pct: r.reduce((s, m) => s + m.labour_pct * m.net_sales, 0) / Math.max(1, ns), cancels: sum(r, "cancels"), avoidable_cancels: sum(r, "avoidable_cancels"),
    by_channel: Object.fromEntries(CHS.map((c) => [c, ns * SHARE[c]])),
    vs_prev_pct: { net_sales: prev.length ? ns / sum(prev, "net_sales") - 1 : null, orders: prev.length ? or / sum(prev, "orders") - 1 : null },
    best_day: sorted[0] ? { date: sorted[0].date, net_sales: sorted[0].net_sales } : null,
    worst_day: sorted.length ? { date: sorted[sorted.length - 1].date, net_sales: sorted[sorted.length - 1].net_sales } : null };
}
function items(a: string, b: string) {
  const r = range(a, b);
  return MENU.map(([item, price, share]) => ({ item, sold: Math.round((r.net_sales * share) / price), net_sales: r.net_sales * share, share }));
}
function day(d: string) {
  return { overview: overviewFor(d), close: d === fx.store.today ? state.close : null,
    report: reports().find((r) => r.date === d && r.kind === "daily") ? { status: "stored", url_html: "/sample-report.pdf", url_pdf: "/sample-report.pdf" } : null };
}
function reports() {
  const out: Record<string, unknown>[] = [];
  const daily = fx.metrics.filter((m) => m.orders > 0).slice(-75).reverse();
  daily.forEach((m, i) => {
    const o = overviewFor(m.date) as { vs_usual: { net_sales_pct: number } | null };
    const v = o.vs_usual?.net_sales_pct ?? 0;
    const urgent = m.date === fx.store.today ? 3 : m.avoidable_cancels > 4 ? 1 : 0;
    out.push({ date: m.date, kind: "daily", status: i < 30 ? "stored" : state.rebuilt.has(m.date) ? "rebuilt" : "expired",
      url_html: "/sample-report.pdf", url_pdf: "/sample-report.pdf",
      headline: `${v > 0.05 ? "Strong" : v < -0.05 ? "Quiet" : "Steady"} ${new Date(`${m.date}T12:00:00`).toLocaleDateString("en-US", { weekday: "long" })}${m.avoidable_cancels > 4 ? ", chashu ran out" : ""}`,
      net_sales: m.net_sales, orders: m.orders, vs_usual_pct: v, urgent, texted: urgent > 0, recoverable_usd: Math.round(((m.cancels * 7) % 60) * 100) / 100 });
  });
  for (const ym of ["2026-10", "2026-09", "2026-08"]) {
    const r = fx.metrics.filter((m) => m.date.startsWith(ym));
    out.push({ date: ym, kind: "monthly", status: state.rebuilt.has(ym) || ym !== "2026-08" ? "stored" : "expired", url_html: "/sample-report.pdf", url_pdf: "/sample-report.pdf",
      headline: "", net_sales: r.reduce((a, m) => a + m.net_sales, 0), orders: r.reduce((a, m) => a + m.orders, 0) });
  }
  return out;
}

function liveStream(q: URLSearchParams, on: Handlers): () => void {
  const d = q.get("date") || fx.store.today;
  const speed = Number(q.get("speed") || 60);
  const from = q.get("from") || "11:00";
  const o = overviewFor(d) as { curve_today: { time: string; orders: number }[]; kpis: { avg_ticket: number } | null };
  if (!o.kpis) { setTimeout(() => on.done?.({}), 50); return () => {}; }
  seed = d.split("-").reduce((a, x) => a * 31 + Number(x), 7) % 2147483647 || 7;
  const toM = (t: string) => { const [h, m] = t.split(":").map(Number); return h * 60 + m; };
  // lay out orders minute by minute from the 15-minute curve
  const orders: { m: number; s: number; ch: string; items: string[]; subtotal: number }[] = [];
  let k = 0;
  for (const p of o.curve_today) {
    const n = Math.round(p.orders);
    for (let i = 0; i < n; i++) {
      const m = toM(p.time) + rnd() * 15;
      const r = rnd(); let acc = 0; let ch = "in_store"; for (const c of CHS) { acc += SHARE[c]; if (r <= acc) { ch = c; break; } }
      const nItems = 1 + Math.floor(rnd() * 2.4);
      const its: string[] = []; let sub = 0;
      for (let j = 0; j < nItems; j++) { const it = MENU[Math.floor(rnd() * MENU.length)]; its.push(it[0]); sub += it[1]; }
      orders.push({ m: Math.floor(m), s: Math.floor((m % 1) * 60), ch, items: its, subtotal: Math.round(sub * 100) / 100 }); k++;
    }
  }
  orders.sort((a, b) => a.m - b.m || a.s - b.s);
  const par = d === fx.store.today ? (fx.guard as { par: number }).par : 560;
  const scale = (o.kpis.avg_ticket * orders.length) / Math.max(1, orders.reduce((a, x) => a + x.subtotal, 0));
  let minute = toM(from), idx = 0;
  const cum = { orders: 0, net: 0, left: par, cancels: 0, by: { in_store: 0, doordash: 0, ubereats: 0, grubhub: 0 } as Record<string, number> };
  const paused = new Set<string>(); let sold = false;
  const fmt = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  // catch up to the start time without emitting orders
  while (idx < orders.length && orders[idx].m < minute) { const x = orders[idx++]; cum.orders++; cum.net += x.subtotal * scale; cum.by[x.ch] += x.subtotal * scale; cum.left -= x.items.filter((i) => /Chashu|Tonkotsu|Shoyu/.test(i)).length * 0.9; }
  const timer = setInterval(() => {
    while (idx < orders.length && orders[idx].m === minute) {
      const x = orders[idx++];
      const needs = x.items.filter((i) => /Chashu|Tonkotsu|Shoyu/.test(i)).length * 0.9;
      let status = "completed";
      if (needs && cum.left < needs) { if (x.ch !== "in_store" && !paused.has(x.ch)) { status = "cancelled"; cum.cancels++; } }
      else { cum.left -= needs; }
      if (status !== "cancelled") { cum.orders++; cum.net += x.subtotal * scale; cum.by[x.ch] += x.subtotal * scale; }
      on.order?.({ t: `${fmt(x.m)}:${String(x.s).padStart(2, "0")}`, id: `m${d}-${x.m}-${x.s}-${idx}`, channel: x.ch, items: x.items, subtotal: Math.round(x.subtotal * scale * 100) / 100, status });
    }
    if (minute === 18 * 60) on.event?.({ t: fmt(minute), kind: "rush_start", text: "Dinner rush started" });
    if (minute === 19 * 60 + 30) on.event?.({ t: fmt(minute), kind: "rush_end", text: "Rush easing off" });
    for (const [app, buf] of [["grubhub", 40], ["doordash", 14], ["ubereats", 14]] as const) {
      if (!paused.has(app) && cum.left < buf) { paused.add(app); on.event?.({ t: fmt(minute), kind: "pause", text: `Chashu paused on ${appName(app)}` }); }
    }
    if (!sold && cum.left <= 1) { sold = true; on.event?.({ t: fmt(minute), kind: "sold_out", text: "Chashu sold out" }); }
    on.tick?.({ t: fmt(minute), orders: cum.orders, net_sales: Math.round(cum.net * 100) / 100, by_channel: Object.fromEntries(Object.entries(cum.by).map(([kk, v]) => [kk, Math.round(v * 100) / 100])), chashu_left: Math.max(0, Math.round(cum.left)), cancels: cum.cancels });
    minute++;
    if (minute > 22 * 60 + 30) { clearInterval(timer); on.done?.({}); }
  }, Math.max(16, 60000 / speed));
  return () => clearInterval(timer);
}
const appName = (a: string) => ({ doordash: "DoorDash", ubereats: "Uber Eats", grubhub: "Grubhub" } as Record<string, string>)[a] || a;

function metricsRange(start: string, end: string) {
  return fx.metrics.filter((m) => m.date >= start && m.date <= end);
}

function askAnswer(q: string) {
  const k = q.trim().toLowerCase();
  const hit = (fx.ask as Record<string, { text: string; clarify: boolean; calls: unknown[] }>)[k];
  if (hit) {
    if (k.includes("last week") || k.includes("forecast been")) {
      const last = fx.metrics.slice(-28);
      return { ...hit, chart: { type: "bar", x: last.map((m) => m.date.slice(5)), series: [{ name: "Orders", values: last.map((m) => m.orders) }] } };
    }
    return hit;
  }
  if (k.includes("chashu") || k.includes("run out")) return (fx.ask as any)["why did we run out of chashu tonight?"];
  return {
    text: "In demo mode I can answer the suggested questions. Start the backend (python -m gondola.api) to ask anything about the last 365 days.",
    clarify: true, calls: [],
  };
}

export const mock = {
  async request(path: string, init?: RequestInit): Promise<unknown> {
    await wait(120);
    const [p, qs] = path.split("?");
    const q = new URLSearchParams(qs || "");
    const body = init?.body ? JSON.parse(String(init.body)) : {};
    if (p === "/health") return { ok: true, version: "mock" };
    if (p === "/store") return fx.store;
    if (p === "/integrations") return { twilio: { live: false }, sendgrid: { live: false }, llm: { live: false }, square: { live: false }, doordash: { live: false } };
    if (p === "/overview") return overviewFor(q.get("date") || fx.store.today);
    if (p === "/metrics/daily") return metricsRange(q.get("start") || "0000", q.get("end") || "9999");
    if (p === "/forecast") return fx.forecast;
    if (p === "/close") return { run_id: `mock-close-${Date.now()}`, date: fx.store.today };
    if (p === "/closes") return state.closed ? [{ date: state.close.date, status: state.close.status, seconds: state.close.seconds,
      findings_count: state.close.findings.length, urgent_count: state.close.findings.filter((f) => f.urgency === "urgent").length }] : [];
    if (p.startsWith("/closes/") && p.endsWith("/approve")) {
      if (body.card) state.close.card = body.card as CardItem[];
      state.close.approved = true;
      return { approved: true, card: state.close.card };
    }
    if (p.startsWith("/closes/")) { if (p.slice(8) !== fx.store.today) throw new Error(`no close for ${p.slice(8)}`); return state.close; }
    if (p === "/reports") return reports();
    if (p === "/metrics/intraday") return intraday(q.get("date") || fx.store.today);
    if (p === "/metrics/items") return items(q.get("start") || fx.store.today, q.get("end") || fx.store.today);
    if (p === "/metrics/range") return range(q.get("start") || fx.store.today, q.get("end") || fx.store.today);
    if (p.startsWith("/day/")) return day(p.slice(5));
    if (p === "/ask") return askAnswer(String(body.question || ""));
    if (p === "/outbox") return state.outbox;
    if (p === "/guard/replay") { const id = `mock-guard-${Date.now()}`; state.runs.set(id, { ...body }); return { run_id: id }; }
    if (p.startsWith("/guard/") && p.endsWith("/recount")) {
      const id = p.split("/")[2]; const r = state.runs.get(id); if (r) r.recount = Number(body.count); return { ok: true };
    }
    throw new Error(`Not found: ${p}`);
  },

  async sms(body: string): Promise<string> {
    const t = body.trim().toLowerCase();
    const now = new Date().toISOString();
    state.outbox.unshift({ channel: "sms", body, ts: now, from: "manager", status: "received" });
    let reply: string;
    if (t === "1") reply = `Cash drawer: expected $${state.close.books.cash.expected?.toFixed(2)}, counted $${state.close.books.cash.counted?.toFixed(2)} (${state.close.books.cash.difference?.toFixed(2)}). Check paid-outs and the last drop.`;
    else if (t === "2") reply = `Wed's DoorDash report: 3 error charges look wrong ($86.40). The checklist with order numbers is in Gondola under Money. Submit in the Merchant Portal within the 14-day window.`;
    else if (t === "3") reply = `Chashu sold out at 8:39 PM and stayed live on the apps for 45 minutes (12 cancels). Tomorrow's card preps ${state.close.card[0]?.prep ?? 770} portions and asks for a recount at about 120 left.`;
    else if (t.startsWith("approve")) { state.close.approved = true; reply = "Approved. Guard will ask for a recount when about 120 chashu portions are left and pause the apps before they run out."; }
    else reply = askAnswer(body).text;
    state.outbox.unshift({ channel: "sms", body: reply, ts: new Date(Date.now() + 1000).toISOString(), from: "gondola", status: "dry_run" });
    return reply;
  },

  reportUrl: (_date: string) => "/sample-report.pdf",
  async rebuild(date: string) { await wait(700); state.rebuilt.add(date); },

  stream(path: string, on: Handlers): () => void {
    if (path.startsWith("/close/")) return closeStream(on);
    if (path.startsWith("/guard/")) return guardStream(path.split("/")[2], on);
    if (path.startsWith("/live/stream")) return liveStream(new URLSearchParams(path.split("?")[1] || ""), on);
    return () => {};
  },
};

function closeStream(on: Handlers): () => void {
  let stopped = false;
  const c = fx.close;
  const books = c.books;
  const lines: [string, string, number, string][] = [
    ["books", "running", 300, "Reading the cash drawer shift and any app payout reports that arrived"],
    ["stock", "running", 100, "Recording confirmed portions"],
    ["demand", "running", 100, "Forecasting tomorrow"],
    ["stock", "done", 500, "Chashu portions confirmed"],
    ["books", "done", 700, `Cash ${books.cash.difference?.toFixed(2)}. Wed's DoorDash report arrived: 3 charges look wrong, checklist drafted`],
    ["demand", "done", 900, `Tomorrow ${Math.round(fx.forecast.p50)} orders, likely ${Math.round(fx.forecast.p10)}–${Math.round(fx.forecast.p90)}`],
    ["analyst", "running", 150, "Comparing with 4 Thursdays and 5 similar rainy game nights"],
    ["analyst", "done", 800, "Net sales -4% vs a usual Thursday. Chashu sold out at 8:39 PM"],
    ["plan", "running", 150, "Sizing tomorrow's prep and pause times"],
    ["plan", "done", 900, `Card ready: make ${c.card[0].prep} chashu, recount at ${c.card[0].recount_at} left`],
    ["sentinel", "running", 100, "Scoring urgency"],
    ["report", "running", 100, "Writing the 2-page report"],
    ["sentinel", "done", 700, "One text sent: 3 things need you"],
    ["report", "done", 600, "Report stored and emailed"],
    ["guard", "running", 100, "Waiting for your approval of tomorrow's card"],
    ["guard", "done", 300, "Rule ready to arm"],
  ];
  const findings = c.findings.filter((f: any) => f.urgency === "urgent" || f.kind === "payout_short").slice(0, 5);
  (async () => {
    let fi = 0;
    for (const [step, status, ms, message] of lines) {
      await wait(ms);
      if (stopped) return;
      on.step?.({ step, status, message, seconds: status === "done" ? Math.round(ms) / 1000 : undefined });
      if (status === "done" && fi < findings.length && ["books", "analyst", "plan"].includes(step)) {
        const take = step === "books" ? 2 : 1;
        for (let i = 0; i < take && fi < findings.length; i++) on.finding?.(findings[fi++]);
      }
    }
    while (fi < findings.length) on.finding?.(findings[fi++]);
    state.closed = true;
    on.done?.({ status: "done", seconds: c.seconds, date: c.date });
  })();
  return () => { stopped = true; };
}

function guardStream(runId: string, on: Handlers): () => void {
  const run = state.runs.get(runId) || {};
  const g = fx.guard as { par: number; orders: { m: number; ch: Channel; need: number; cancel: boolean }[]; status_quo_cancels: number };
  const params = new URLSearchParams(runId.split("?")[1] || "");
  const speed = Number((run as any).speed || params.get("speed") || 300);
  const countError = 0.06; // the kitchen made 6% fewer portions than Gondola believes
  let trueLeft = g.par * (1 - countError);
  let believed = g.par;
  const sold: Record<Channel, number> = { in_store: 0, doordash: 0, ubereats: 0, grubhub: 0 };
  const available: Record<Channel, boolean> = { in_store: true, doordash: true, ubereats: true, grubhub: true };
  const pauseDelay: Record<string, number> = { doordash: 2, ubereats: 2, grubhub: 10 };
  const pauseAt: Record<string, number | null> = { doordash: null, ubereats: null, grubhub: null };
  let cancels = 0, held = 0, prompted = false, promptMin = 0, counted = false;
  const start = 17 * 60, end = 22 * 60 + 30;
  const orders = g.orders.filter((o) => o.m >= 11 * 60);
  // stock already used before the replay window
  for (const o of orders) if (o.m < start && !o.cancel) { trueLeft -= o.need; believed -= o.need; sold[o.ch] += o.need; }
  let minute = start;
  let rate = 0;
  const fmt = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(m % 60).padStart(2, "0")}`;
  const timer = setInterval(() => {
    const r = state.runs.get(runId) as any;
    if (prompted && !counted && (r?.recount !== undefined || minute - promptMin >= 20)) {
      believed = r?.recount !== undefined ? r.recount : Math.max(0, Math.round(trueLeft) + 1);
      counted = true;
      on.step?.({ message: `Recount: ${Math.round(believed)} portions` });
    }
    const now = orders.filter((o) => o.m === minute);
    let used = 0;
    for (const o of now) {
      if (o.ch !== "in_store" && !available[o.ch]) { held += o.need; continue; }
      if (trueLeft >= o.need) { trueLeft -= o.need; believed -= o.need; sold[o.ch] += o.need; used += o.need; }
      else if (o.ch !== "in_store") cancels += 1;
      else available.in_store = trueLeft > 0.5;
    }
    rate = 0.7 * rate + 0.3 * used;
    if (!prompted && believed < 120) { prompted = true; promptMin = minute; on.recount_prompt?.({ believed_left: Math.round(believed), t: fmt(minute) }); }
    for (const app of ["doordash", "ubereats", "grubhub"] as const) {
      if (pauseAt[app] === null && believed < 8 + rate * pauseDelay[app] * 0.66) {
        pauseAt[app] = minute + pauseDelay[app];
      }
      if (pauseAt[app] !== null && minute >= (pauseAt[app] as number) && available[app]) {
        available[app] = false; on.pause?.({ app, t: fmt(minute) });
      }
    }
    if (trueLeft < 1) available.in_store = false;
    on.tick?.({ t: fmt(minute), believed_left: Math.max(0, Math.round(believed)), sold: { ...sold }, available: { ...available }, cancels, held_back: Math.round(held) });
    minute += 1;
    if (minute > end) { clearInterval(timer); on.done?.({ cancels, held_back: Math.round(held), status_quo_cancels: g.status_quo_cancels }); }
  }, Math.max(20, 60000 / speed));
  return () => clearInterval(timer);
}
