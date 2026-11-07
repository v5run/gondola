/** Sample data for the Past / Present / Future / Review endpoints, used only when the backend is offline (or VITE_MOCK=1).
 *  Deterministic per date and driven by the real clock: outside service hours the sample clock starts at 7:30 pm on
 *  page load and runs in real time, so the queue still moves like a live night. Shapes follow TRI_WORKFLOW_API.md. */
import { toMin } from "../lib/dates";
import type {
  Action, ActionItem, ContextPayload, DayReview, Digest, ExceptionItem, FutureDay, FutureDriver, FutureToday, KbItem, LedgerEvent,
  LimitedItem, PastSummary, PresentSettings, PresentState, QueueRow, Station,
} from "./tri";

type Point = { time: string; orders: number };
type Handlers = Record<string, (data: any) => void>;

/* ---------------- clock ---------------- */
const LOAD = Date.now();
const realMin = () => { const d = new Date(); return d.getHours() * 60 + d.getMinutes() + d.getSeconds() / 60; };
const ANCHOR = (() => { const m = realMin(); return m >= 11 * 60 + 30 && m <= 21 * 60 + 45 ? null : 19 * 60 + 30; })();
/** Minutes since midnight on the sample clock (fractional). */
export const sampleMin = () => (ANCHOR === null ? realMin() : ANCHOR + (Date.now() - LOAD) / 60000);
const hm = (m: number) => { const x = Math.max(0, Math.floor(m)); return `${String(Math.floor(x / 60) % 24).padStart(2, "0")}:${String(x % 60).padStart(2, "0")}`; };
const hms = (m: number) => `${hm(m)}:${String(Math.floor((m % 1) * 60)).padStart(2, "0")}`;
const OPEN = 11 * 60, CLOSE = 22 * 60;

/* ---------------- menu & world ---------------- */
const MENU: [string, string, number, number, number][] = [ // name, station, minutes, price, weight
  ["Tonkotsu", "noodles", 4.5, 19.25, 26], ["Spicy Miso", "noodles", 4.5, 19.25, 15], ["Shoyu", "noodles", 4, 18.15, 11], ["Tantanmen", "noodles", 5, 19.8, 9],
  ["Chicken Paitan", "noodles", 5, 18.7, 6], ["Veggie Miso", "noodles", 4, 17.6, 4], ["Gyoza", "fryer", 4, 8.8, 10], ["Karaage", "fryer", 6, 10.45, 7],
  ["Takoyaki", "fryer", 3, 9.35, 3], ["Chashu Don", "assembly", 3, 15.4, 8], ["Chashu Bao", "assembly", 2, 9.35, 7], ["Edamame", "assembly", 1, 6.05, 3],
  ["Mochi Trio", "assembly", 1, 7.7, 2], ["Sapporo", "drinks", 0, 7.0, 3],
];
const WSUM = MENU.reduce((a, m) => a + m[4], 0);
const SHARE: [string, number][] = [["doordash", 0.31], ["ubereats", 0.2], ["grubhub", 0.11], ["pickup", 0.13], ["dine_in", 0.25]];
const STATIONS: [string, string][] = [["noodles", "Noodles"], ["fryer", "Fryer"], ["assembly", "Assembly"], ["packing", "Packing"]];
const hash = (s: string) => { let h = 2166136261; for (let i = 0; i < s.length; i++) { h ^= s.charCodeAt(i); h = Math.imul(h, 16777619); } return (h >>> 0) / 4294967296; };
const rng = (seed: string) => { let i = 0; return () => hash(`${seed}:${i++}`); };

interface Ord {
  id: string; t: number; channel: string; items: string[]; subtotal: number; fulfillment: string; promise: number; courier: number | null;
  dist: number | null; cdist: number | null; cook: number; station: string; due: number; latestStart: number; start: number; end: number; handoff: number;
  cancelled: boolean;
}

let curveOf: (d: string) => Point[] = () => [];
let todayIso = "";
export function initTri(curve: (d: string) => Point[], today: string) { curveOf = curve; todayIso = today; }

const cache = new Map<string, Ord[]>();
/** Every order of a day, placed minute by minute from the day's 15-minute curve, with a simple shared-kitchen schedule. */
function orders(date: string): Ord[] {
  const hit = cache.get(date); if (hit) return hit;
  const r = rng(date);
  const out: Ord[] = [];
  let n = 0;
  for (const p of curveOf(date)) {
    const [h, m] = p.time.split(":").map(Number);
    const k = Math.round(p.orders);
    for (let i = 0; i < k; i++) {
      const t = h * 60 + m + r() * 15;
      let x = r(), channel = "dine_in"; for (const [c, s] of SHARE) { x -= s; if (x <= 0) { channel = c; break; } }
      const items: string[] = []; let sub = 0, cook = 0, station = "assembly";
      const ni = 1 + Math.floor(r() * 2.6);
      for (let j = 0; j < ni; j++) {
        let w = r() * WSUM; let it = MENU[0]; for (const mm of MENU) { w -= mm[4]; if (w <= 0) { it = mm; break; } }
        items.push(it[0]); sub += it[3];
        if (it[2] > cook) { cook = it[2]; station = it[1]; }
      }
      const delivery = ["doordash", "ubereats", "grubhub"].includes(channel);
      const fulfillment = delivery ? "delivery" : channel === "pickup" ? "pickup" : "dine_in";
      const promise = t + (delivery ? 15 + r() * 10 : channel === "pickup" ? 15 + r() * 5 : 9 + r() * 3);
      const courier = delivery ? t + 9 + r() * 20 : null;
      const id = `${channel === "doordash" ? "DD" : channel === "ubereats" ? "UE" : channel === "grubhub" ? "GH" : channel === "pickup" ? "PK" : "DI"}-${String(1000 + n++).slice(1)}`;
      out.push({ id, t, channel, items, subtotal: Math.round(sub * 100) / 100, fulfillment, promise, courier, dist: delivery ? Math.round((0.4 + r() * 5) * 10) / 10 : null,
        cdist: delivery ? Math.round((0.5 + r() * 6.5) * 10) / 10 : null, cook: cook + 1, station, due: 0, latestStart: 0, start: 0, end: 0, handoff: 0, cancelled: r() < 0.012 });
    }
  }
  out.sort((a, b) => a.t - b.t);
  // a shared kitchen: each order takes one slot on its main station (6 noodle baskets, 4 fryer baskets, 3 assembly spots)
  const slots: Record<string, number[]> = { noodles: Array(6).fill(OPEN), fryer: Array(4).fill(OPEN), assembly: Array(3).fill(OPEN), drinks: Array(3).fill(OPEN) };
  for (const o of out) {
    o.due = o.courier !== null ? Math.min(o.promise + 3, Math.max(o.promise - 2, o.courier)) : o.promise;
    o.latestStart = o.due - o.cook;
    const sl = slots[o.station]; sl.sort((a, b) => a - b);
    const want = Math.max(o.t + 0.5, o.latestStart - (o.station === "fryer" ? 1.5 : 4));
    o.start = Math.max(want, sl[0]);
    o.end = o.start + o.cook;
    sl[0] = o.end - 1; // packing overlaps the next start
    o.handoff = Math.max(o.end, o.courier ?? o.promise) + (o.fulfillment === "delivery" ? 0.5 : 0.2);
  }
  cache.set(date, out);
  return out;
}

const isToday = (d: string) => d === todayIso;
const nowFor = (d: string) => (isToday(d) ? Math.min(sampleMin(), CLOSE + 30) : d < todayIso ? CLOSE + 60 : OPEN - 60);

/* ---------------- settings ---------------- */
const settings: PresentSettings = {
  ladder: { promote_above: 20, quote_below: 0, pause_below: -10, busy_below: -25, hysteresis_min: 2 },
  weights: { courier: 1, distance: 0.6, hold: 0.8, weather: 0.5, batch: 0.7, fairness: 1, in_store: 1 },
  max_wait_min: 35,
};
const LEVELS = ["promote", "normal", "quote", "pause_items", "busy"] as const;
const LEVEL_NAME: Record<string, string> = { promote: "Promote", normal: "Normal", quote: "Quote longer", pause_items: "Pause slow items", busy: "Busy mode" };
const levelOf = (h: number) => { const L = settings.ladder; return h > L.promote_above ? "promote" : h >= L.quote_below ? "normal" : h >= L.pause_below ? "quote" : h >= L.busy_below ? "pause_items" : "busy"; };

function headroomAt(date: string, m: number) {
  const os = orders(date);
  const rate = os.filter((o) => o.t > m - 15 && o.t <= m).length / 15;
  const queued = os.filter((o) => o.t <= m && o.start > m).length;
  const wobble = Math.sin(m / 7) * 2.5 + Math.sin(m / 2.3) * 1.2;
  return Math.max(-42, Math.min(38, 34 - rate * 22 - queued * 0.6 + wobble));
}

/** Ladder actions through the day: the level is re-read every minute and must hold 2+ minutes before it moves. */
function ladderLog(date: string, upTo: number): { at: number; level: string; head: number }[] {
  const log: { at: number; level: string; head: number }[] = [];
  let cur = "normal", cand = "normal", since = OPEN;
  for (let m = OPEN; m <= Math.min(upTo, CLOSE); m += 1) {
    const h = headroomAt(date, m);
    const l = levelOf(h);
    if (l !== cand) { cand = l; since = m; }
    if (cand !== cur && m - since >= settings.ladder.hysteresis_min) { cur = cand; log.push({ at: m, level: cur, head: h }); }
  }
  return log;
}

function channelsFor(level: string, head: number): PresentState["channels"] {
  const extra = Math.max(4, Math.round(-head / 2) + 4);
  const open = { state: "open" };
  if (level === "quote") return { doordash: { state: "quoted", quoted_extra_min: extra }, ubereats: { state: "quoted", quoted_extra_min: extra }, grubhub: { state: "quoted", quoted_extra_min: extra + 2 }, pickup: open, dine_in: open };
  if (level === "pause_items") return { doordash: { state: "quoted", quoted_extra_min: extra }, ubereats: { state: "paused_items", paused_items: ["Karaage"] }, grubhub: { state: "paused_items", paused_items: ["Karaage", "Gyoza"] }, pickup: { state: "quoted", quoted_extra_min: 5 }, dine_in: open };
  if (level === "busy") return { doordash: { state: "paused_items", paused_items: ["Karaage", "Gyoza"] }, ubereats: { state: "busy" }, grubhub: { state: "busy" }, pickup: { state: "quoted", quoted_extra_min: 10 }, dine_in: open };
  return { doordash: open, ubereats: open, grubhub: open, pickup: open, dine_in: open };
}

const ACT_OF: Record<string, string> = { promote: "promote", normal: "resume", quote: "quote", pause_items: "pause_item", busy: "busy" };
const agentActions: Action[] = [];
function actionsFor(date: string, m: number): Action[] {
  const log = ladderLog(date, m);
  const out: Action[] = log.map((l, i) => {
    const prev = i ? log[i - 1].level : "normal";
    const up = LEVELS.indexOf(l.level as never) < LEVELS.indexOf(prev as never);
    const reason = l.level === "promote" ? "Fryer and assembly idle for the next 30 min; featuring Karaage within budget"
      : l.level === "normal" ? `Headroom back above ${settings.ladder.quote_below}%`
        : l.level === "quote" ? `Headroom ${Math.round(l.head)}%: quoting delivery ${Math.max(4, Math.round(-l.head / 2) + 4)} min longer`
          : l.level === "pause_items" ? "Fryer booked 24 min ahead; pausing Karaage and Gyoza on Grubhub first (slowest to pause)"
            : "Below −25%: Uber Eats and Grubhub to busy, cheapest contribution first. Dine-in untouched";
    return { ts: `${date}T${hm(l.at)}:00`, action: ACT_OF[l.level], channel: l.level === "pause_items" ? "grubhub" : l.level === "busy" ? "ubereats" : null,
      item: l.level === "pause_items" ? "Karaage" : null, ladder_level: l.level, headroom_pct: Math.round(l.head * 10) / 10, reason: up && l.level === "normal" ? "Headroom recovered" : reason, by: "controller" };
  });
  return [...out, ...agentActions.filter((a) => a.ts?.startsWith(date))].sort((a, b) => String(b.ts).localeCompare(String(a.ts)));
}

function queueAt(date: string, m: number, rain: boolean): QueueRow[] {
  const os = orders(date).filter((o) => o.t <= m && o.handoff > m && !o.cancelled);
  const rows = os.map((o) => {
    const status = m < o.start ? "queued" : m < o.end - 1 ? "cooking" : m < o.end ? "packing" : "ready";
    const fried = o.items.some((i) => ["Gyoza", "Karaage", "Takoyaki"].includes(i));
    const age = m - o.t;
    const f = {
      courier: o.courier !== null ? Math.round(Math.max(-4, Math.min(8, o.courier - o.promise)) * 10) / 10 : 0,
      distance: o.cdist !== null && o.cdist > 4 ? -1.5 : o.cdist !== null && o.cdist < 1.5 ? 1 : 0,
      hold: fried ? 1.5 : o.items.includes("Chashu Don") ? -1 : 0,
      weather: rain && o.fulfillment === "delivery" ? -1.2 : 0,
      batch: os.some((x) => x !== o && x.station === o.station && Math.abs(x.due - o.due) < 3) ? -0.8 : 0,
      fairness: age > 25 ? -Math.round((age - 25) * 10) / 10 : 0,
      in_store: o.fulfillment === "dine_in" ? -3 : o.fulfillment === "pickup" && m > o.promise - 2 ? -2 : 0,
    };
    const slack = o.latestStart - m;
    const prio = slack + Object.values(f).reduce((a, v) => a + v, 0);
    const top = Object.entries(f).filter(([, v]) => v !== 0).sort((a, b) => Math.abs(b[1]) - Math.abs(a[1]))[0];
    const why: Record<string, string> = {
      courier: f.courier > 0 ? `Courier ${Math.round((o.courier ?? m) - m)} min out, so it can wait` : "Courier arriving before the promise",
      distance: f.distance < 0 ? "Long drive: finish close to pickup" : "Short drive: no holding penalty",
      hold: f.hold > 0 ? "Fried items start as late as possible" : "Holds well, can start early",
      weather: "Rain makes courier ETAs noisier: small buffer", batch: "Batched with another order on the same station",
      fairness: `Waiting ${Math.round(age)} min: fairness cap pulls it forward`, in_store: o.fulfillment === "dine_in" ? "Guest is in the restaurant" : "Customer is here",
    };
    const reason = status !== "queued" ? (status === "ready" ? (o.courier !== null ? `Ready, courier ${o.courier > m ? `${Math.round(o.courier - m)} min out` : "arriving"}` : "Ready for the guest") : "On the line: work in progress never moves")
      : top ? `${why[top[0]]}. Slack ${Math.round(slack)} min` : `Ordered by slack: ${Math.round(slack)} min`;
    return { o, status, prio, row: {
      rank: 0, order_id: o.id, channel: o.channel, items: o.items, fulfillment: o.fulfillment, promise: hm(o.promise), courier_eta: o.courier !== null ? hm(o.courier) : null,
      courier_distance_km: o.dist !== null && o.courier !== null ? Math.round(o.dist * Math.max(0, Math.min(1, (o.courier - m) / Math.max(1, o.courier - o.t))) * 10) / 10 : null,
      customer_distance_km: o.cdist, due: hm(o.due), latest_start: hm(o.latestStart), slack_min: Math.round(slack * 10) / 10, station: o.station, status, factors: f, reason,
    } as QueueRow };
  });
  const order = { packing: 0, cooking: 1, ready: 3, queued: 2 } as Record<string, number>;
  rows.sort((a, b) => order[a.status] - order[b.status] || a.prio - b.prio);
  rows.forEach((r, i) => { r.row.rank = i + 1; });
  return rows.map((r) => r.row);
}

function stationsAt(date: string, m: number, rain: boolean): Station[] {
  const os = orders(date).filter((o) => o.end > m - 20 && o.start < m + 45 && o.t <= m && !o.cancelled);
  void rain;
  return STATIONS.map(([key, name]) => ({
    key, name, speed: key === "fryer" && m > 17 * 60 + 42 && m < 18 * 60 + 10 ? 0.5 : 1,
    busy_until: (() => { const e = os.filter((o) => o.station === key || key === "packing").map((o) => (key === "packing" ? o.end : o.end - 1)); return e.length ? hm(Math.max(m, ...e)) : null; })(),
    tasks: os.filter((o) => (key === "packing" ? o.cook > 0 : o.station === key)).map((o) => key === "packing"
      ? { order_id: o.id, item: "Pack", start: hm(o.end - 1), end: hm(o.end), frozen: o.end - 1 <= m, channel: o.channel }
      : { order_id: o.id, item: o.items.find((i) => MENU.find((x) => x[0] === i)?.[1] === key) || o.items[0], start: hm(o.start), end: hm(o.end - 1), frozen: o.start <= m, channel: o.channel }),
  }));
}

function compareAt(date: string, m: number) {
  const done = orders(date).filter((o) => o.handoff <= m && !o.cancelled);
  const n = done.length;
  if (!n) return { fifo: { promises_met: null, avg_wait: null, worst_wait: null, hold: null }, gondola: { promises_met: null, avg_wait: null, worst_wait: null, hold: null }, orders: 0 };
  const late = done.filter((o) => o.end > o.due + 0.5).length;
  const waits = done.map((o) => Math.max(0, (o.courier ?? o.promise) - o.end));
  const hold = done.map((o) => Math.max(0, o.handoff - o.end));
  const avg = (a: number[]) => a.reduce((x, y) => x + y, 0) / a.length;
  const g = { promises_met: Math.round((1 - late / n) * 1000) / 1000, avg_wait: Math.round(avg(waits) * 10) / 10, worst_wait: Math.round(Math.max(...waits) * 10) / 10, hold: Math.round(avg(hold) * 10) / 10 };
  const f = { promises_met: Math.round(Math.max(0.5, g.promises_met - 0.11 - 0.04 * hash(date)) * 1000) / 1000, avg_wait: Math.round((g.avg_wait * 1.55 + 1.2) * 10) / 10,
    worst_wait: Math.round((g.worst_wait * 1.7 + 4) * 10) / 10, hold: Math.round((g.hold * 2.1 + 1.4) * 10) / 10 };
  return { fifo: f, gondola: g, orders: n };
}

function presentState(date: string, m = nowFor(date)): PresentState {
  const rain = hash(`${date}rain`) < 0.4;
  const head = m > CLOSE ? 30 : headroomAt(date, m);
  const log = ladderLog(date, m);
  const level = m > CLOSE ? "normal" : log.length ? log[log.length - 1].level : "normal";
  const L = settings.ladder;
  const next: Record<string, number | null> = { promote: L.promote_above, normal: head >= 10 ? L.promote_above : L.quote_below, quote: L.pause_below, pause_items: L.busy_below, busy: L.busy_below };
  const cmp = compareAt(date, m);
  return {
    date, now: isToday(date) ? hms(m) : hm(m), phase: m < OPEN ? "before_open" : m > CLOSE ? "closed" : "open", headroom_pct: Math.round(head * 10) / 10,
    ladder: { level, name: LEVEL_NAME[level], since: log.length ? hm(log[log.length - 1].at) : hm(OPEN), next_threshold: next[level] },
    queue: m > CLOSE + 20 ? [] : queueAt(date, m, rain), stations: stationsAt(date, m, rain), channels: channelsFor(level, head),
    actions: actionsFor(date, m).slice(0, 30), weather: { rain, temp_c: Math.round(4 + hash(`${date}t`) * 8), source: "calendar" },
    compare: { fifo: cmp.fifo, gondola: cmp.gondola },
  };
}

function presentStream(q: URLSearchParams, on: Handlers): () => void {
  const date = q.get("date") || todayIso;
  let seen = new Set(orders(date).filter((o) => o.t <= nowFor(date)).map((o) => o.id));
  let acts = actionsFor(date, nowFor(date)).length;
  const push = () => on.state?.(presentState(date));
  const t0 = setTimeout(push, 60);
  const id = setInterval(() => {
    const m = nowFor(date);
    const fresh = orders(date).filter((o) => o.t <= m && !seen.has(o.id));
    const st = presentState(date);
    for (const o of fresh) { const r = st.queue.find((x) => x.order_id === o.id); on.order?.({ order_id: o.id, channel: o.channel, items: o.items, rank: r?.rank ?? null, ts: hm(o.t) }); }
    seen = new Set([...seen, ...fresh.map((o) => o.id)]);
    const a = actionsFor(date, m);
    if (a.length > acts) on.action?.(a[0]);
    acts = a.length;
    on.state?.(st);
    if (m > CLOSE + 30) { clearInterval(id); on.done?.({}); }
  }, 5000);
  return () => { clearTimeout(t0); clearInterval(id); };
}

/* ---------------- Past ---------------- */
function pastSummary(date: string, m = nowFor(date)): PastSummary {
  const os = orders(date).filter((o) => o.t <= m);
  const done = os.filter((o) => o.handoff <= m && !o.cancelled);
  const by: PastSummary["by_channel"] = {};
  for (const [c] of SHARE) by[c] = { orders: 0, sales: 0 };
  for (const o of os.filter((x) => !x.cancelled)) { by[o.channel].orders++; by[o.channel].sales = Math.round((by[o.channel].sales + o.subtotal) * 100) / 100; }
  const waits = done.map((o) => Math.max(0, (o.courier ?? o.promise) - o.end));
  const hold = done.map((o) => Math.max(0, o.handoff - o.end));
  const met = done.filter((o) => o.end <= o.due + 0.5).length;
  const avg = (a: number[]) => (a.length ? Math.round((a.reduce((x, y) => x + y, 0) / a.length) * 10) / 10 : null);
  return { date, cutoff: isToday(date) ? hm(m) : null, processed: done.length, by_channel: by, promises_met: met, promises_total: done.length,
    avg_wait_min: avg(waits), worst_wait_min: waits.length ? Math.round(Math.max(...waits) * 10) / 10 : null, avg_hold_min: avg(hold),
    cancels: os.filter((o) => o.cancelled).length, refunds: Math.floor(os.length / 140), actions_count: actionsFor(date, m).length };
}

function ledgerEvents(date: string, m = nowFor(date)): LedgerEvent[] {
  const ev: LedgerEvent[] = [];
  let id = 1;
  const add = (min: number, type: string, payload: Record<string, any>, source: string) => { if (min <= m) ev.push({ id: 0, date, ts: `${date}T${hms(min)}`, type, source, key: `${type}:${id++}`, payload }); };
  for (const o of orders(date)) {
    add(o.t, "order.received", { order_id: o.id, channel: o.channel, items: o.items, subtotal: o.subtotal, promise: hm(o.promise), fulfillment: o.fulfillment, customer_distance_km: o.cdist, courier_eta: o.courier !== null ? hm(o.courier) : null }, `adapter:${o.channel}`);
    if (o.cancelled) { add(o.t + 4, "order.cancelled", { order_id: o.id, channel: o.channel, reason: "Customer cancelled", amount: o.subtotal }, `adapter:${o.channel}`); continue; }
    add(o.t + 0.2, "order.accepted", { order_id: o.id, reason: "Within capacity", ladder_level: "normal" }, "present");
    add(o.start, "task.started", { order_id: o.id, task_id: `${o.id}-1`, item: o.items[0], station: o.station, planned_min: o.cook - 1 }, "kitchen");
    add(o.end, "task.finished", { order_id: o.id, task_id: `${o.id}-1`, item: o.items[0], station: o.station, planned_min: o.cook - 1, actual_min: Math.round((o.cook - 1 + (hash(o.id) - 0.4) * 2) * 10) / 10 }, "kitchen");
    if (o.courier !== null) add(o.courier, "courier.arrived", { order_id: o.id, channel: o.channel, eta: hm(o.courier) }, `adapter:${o.channel}`);
    add(o.handoff, "order.handed_off", { order_id: o.id, channel: o.channel, ready: hm(o.end), handed: hm(o.handoff), wait_min: Math.round(Math.max(0, (o.courier ?? o.promise) - o.end) * 10) / 10, hold_min: Math.round(Math.max(0, o.handoff - o.end) * 10) / 10, late_min: Math.round(Math.max(0, o.end - o.due) * 10) / 10 }, "present");
  }
  for (const a of actionsFor(date, m)) { const [h, mm] = String(a.ts).slice(11, 16).split(":").map(Number); add(h * 60 + mm, "action.applied", a, a.by === "controller" ? "present" : "review"); }
  for (const x of exceptionsFor(date, m)) { const [h, mm] = x.ts.slice(11, 16).split(":").map(Number); add(h * 60 + mm, "exception.raised", x, "review"); }
  ev.sort((a, b) => a.ts.localeCompare(b.ts));
  ev.forEach((e, i) => { e.id = i + 1; });
  return ev.reverse();
}

/* ---------------- Future ---------------- */
const BASE_DRIVERS = (date: string): FutureDriver[] => {
  const dow = new Date(`${date}T12:00:00`).getDay();
  const out: FutureDriver[] = [];
  if (dow === 4 || dow === 6 || hash(`${date}g`) < 0.3) out.push({ kind: "game", label: "Penguins home game", time: "19:00", window: "19:00–21:30", effect_pct: 8.0, channel_note: "delivery", why: "Weekday Penguins home games raised delivery orders 8% after puck drop on 3 past nights (Oct 8, Oct 22, Nov 5).", estimate: false });
  if (hash(`${date}rain`) < 0.4) out.push({ kind: "weather", label: "Rain from 6 pm", time: "18:00", window: "18:00–22:00", effect_pct: 6.0, channel_note: "delivery +11%, dine-in −4%", why: "Rainy evenings move orders to delivery: +11% on the apps and −4% dine-in across 14 rainy weekday dinners.", estimate: false });
  if (hash(`${date}c`) < 0.35) out.push({ kind: "event", label: "Concert at PPG Paints Arena", time: "20:00", window: null, effect_pct: 3.0, channel_note: null, why: "No past examples at this venue on a weekday. Small bump assumed from similar arena nights; treat as uncertain.", estimate: true });
  out.push({ kind: "school", label: "Pitt midterms", time: null, window: null, effect_pct: -3.0, channel_note: "late night", why: "Exam weeks shave about 3% off late orders (2 past examples).", estimate: true });
  out.push({ kind: "weekday", label: dow === 5 || dow === 6 ? "Weekend dinner" : "Weekday pattern", time: null, window: null, effect_pct: 0, channel_note: null, why: "The baseline: the last 8 same weekdays.", estimate: false });
  return out;
};
const CHS5 = ["doordash", "ubereats", "grubhub", "pickup", "dine_in"];
function futureToday(date: string, m = nowFor(date)): FutureToday {
  const curve = curveOf(date);
  const drivers = BASE_DRIVERS(date);
  const lift = 1 + drivers.reduce((a, d) => a + d.effect_pct / 100, 0) * 0.4;
  const bins = curve.flatMap((p) => CHS5.map((c) => {
    const share = SHARE.find((s) => s[0] === c)![1];
    const p50 = Math.round(p.orders * share * lift * 10) / 10;
    const [h, mm] = p.time.split(":").map(Number); const t = h * 60 + mm;
    const actual = t + 15 <= m ? orders(date).filter((o) => o.channel === c && o.t >= t && o.t < t + 15).length : null;
    return { time: p.time, channel: c, p10: Math.round(p50 * 0.7 * 10) / 10, p50, p90: Math.round(p50 * 1.35 * 10) / 10, actual };
  }));
  const total = bins.reduce((a, b) => a + b.p50, 0);
  const soFar = orders(date).filter((o) => o.t <= m).length;
  const expBy = bins.reduce((a, b) => { const [h, mm] = b.time.split(":").map(Number); return a + b.p50 * Math.max(0, Math.min(1, (m - h * 60 - mm) / 15)); }, 0);
  const restP50 = bins.reduce((a, b) => { const [h, mm] = b.time.split(":").map(Number); return a + b.p50 * (1 - Math.max(0, Math.min(1, (m - h * 60 - mm) / 15))); }, 0) * (expBy > 0 ? 0.5 + 0.5 * soFar / expBy : 1);
  return {
    date, now: hm(m), so_far: { orders: soFar, expected_by_now: Math.round(expBy * 10) / 10, vs_expected_pct: expBy > 0 ? (soFar / expBy - 1) * 100 : null },
    expected: { p10: Math.round(total * 0.86), p50: Math.round(total), p90: Math.round(total * 1.13) },
    rest: { p10: Math.round(restP50 * 0.8), p50: Math.round(restP50), p90: Math.round(restP50 * 1.2) },
    bins, drivers, adjustments: outlookAdj.filter((a) => a.date === date).map(({ date: _d, ...a }) => a),
  };
}
const ITEMS: [string, string, string, number, number][] = [["chashu", "Chashu", "portions", 150, 10], ["egg", "Ajitama egg", "eggs", 120, 12], ["gyoza", "Gyoza", "pieces", 360, 30], ["broth", "Tonkotsu broth", "litres", 38, 4]];
function itemsAt(date: string, m = nowFor(date)): LimitedItem[] {
  const os = orders(date).filter((o) => o.t <= m && !o.cancelled);
  const used = { chashu: 0, egg: 0, gyoza: 0, broth: 0 } as Record<string, number>;
  for (const o of os) for (const i of o.items) {
    if (/Chashu|Tonkotsu|Shoyu/.test(i)) used.chashu += 1;
    if (/Tonkotsu|Spicy Miso|Shoyu/.test(i)) used.egg += 0.7;
    if (i === "Gyoza") used.gyoza += 6;
    if (/Tonkotsu|Tantanmen/.test(i)) used.broth += 0.42;
  }
  const rate = (k: string) => Math.max(0.05, os.filter((o) => o.t > m - 30).length / 30) * ({ chashu: 0.45, egg: 0.35, gyoza: 0.7, broth: 0.16 } as Record<string, number>)[k];
  return ITEMS.map(([key, name, unit, made]) => {
    const left = Math.max(0, Math.round((made - used[key]) * 10) / 10);
    const run = m < CLOSE && left > 0 ? m + left / rate(key) : null;
    const ro = run !== null && run < CLOSE ? run : null;
    return { key, name, unit, made, believed_left: Math.round(left), projected_runout: left <= 0 ? hm(m) : ro ? hm(ro) : null,
      pause_at: ro ? { doordash: hm(ro - 6), ubereats: hm(ro - 6), grubhub: hm(ro - 14) } : { doordash: null, ubereats: null, grubhub: null },
      recount_at: Math.round(made * 0.2) };
  });
}
function futureDays(start: string, n: number, store: { p50Of: (d: string) => number }): FutureDay[] {
  const out: FutureDay[] = [];
  for (let i = 0; i < n; i++) {
    const d = new Date(`${start}T12:00:00`); d.setDate(d.getDate() + i);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const p50 = store.p50Of(iso);
    const w = 0.12 + i * 0.025;
    out.push({ date: iso, p50: Math.round(p50), p10: Math.round(p50 * (1 - w)), p90: Math.round(p50 * (1 + w * 1.1)), rush: { start: "18:00", end: "19:45" },
      drivers: BASE_DRIVERS(iso).filter((x) => i < 2 || x.kind !== "weather"), weather_known: i < 2,
      cards: ITEMS.map(([key, name, unit, made, batch]) => {
        const target = Math.round((made * p50) / 210 / batch) * batch;
        const onHand = key === "broth" ? 6 : key === "chashu" && i === 0 ? 12 : 0;
        const prep = Math.max(0, Math.ceil((target - onHand) / batch) * batch);
        return { item: name, key, unit, target, prep, on_hand: onHand, batch, recount_at: Math.round(target * 0.2),
          pause_at: { doordash: "21:05", ubereats: "21:05", grubhub: "20:55" }, pause_if_busy: { doordash: "20:10", ubereats: "20:10", grubhub: "19:58" } };
      }) });
  }
  return out;
}
const outlookAdj: { date: string; driver: string; pct: number; evidence: string | string[]; by: string }[] = [];

/* ---------------- Review ---------------- */
const resolved = new Set<string>();
function exceptionsFor(date: string, at?: number): ExceptionItem[] {
  const m = at ?? nowFor(date);
  const all: [number, string, string, string, string, string][] = [
    [17 * 60 + 44, "station_incident", "high", "Fryer at half speed since 5:42 pm", "present", "Karaage and Gyoza paused on Grubhub until the fryer recovers."],
    [18 * 60 + 21, "late_order", "high", "DD-142 is 12 min past due", "alert", "Courier waited 12 min. Texted the manager (bundled with the fryer note)."],
    [18 * 60 + 58, "cancel_cluster", "warn", "3 Uber Eats cancels in 20 min", "note", "All three were long-distance orders quoted +9 min. Noted for the close review."],
    [19 * 60 + 12, "forecast_miss", "warn", "Orders 14% above the forecast's top range", "present", "Nowcast raised the rest of tonight; ladder thresholds unchanged."],
    [19 * 60 + 26, "late_order", "info", "PK-188 ready 4 min after promise", "note", "Guest was already waiting. Within tolerance; noted."],
    [20 * 60 + 40, "payout_mismatch", "high", "DoorDash payout $86.40 short for Nov 4", "alert", "3 error charges look wrong. Dispute checklist drafted under Money."],
  ];
  return all.filter((a) => a[0] <= m || (at === undefined && date < todayIso)).map(([t, kind, severity, title, decision, note], i) => {
    const id = `ex-${date.replace(/-/g, "").slice(4)}-${i + 1}`;
    return { id, ts: `${date}T${hm(t)}:00`, kind, severity, title, decision, note, resolved: resolved.has(id) || (date < todayIso && i % 3 !== 1) };
  }).reverse();
}
function dayReview(date: string): DayReview {
  if (date >= todayIso && nowFor(date) < CLOSE + 30) return { date, status: "open", well: [], wrong: [], causes: [], actions: [], kb_changes: [], digest_id: null };
  const d = date.replace(/-/g, "").slice(4);
  return {
    date, status: "done",
    well: [
      { text: "92% of promises met across 218 orders, up from 86% on the last four Thursdays", evidence: ["promises 201/218", "2026-10-29", "2026-10-22"] },
      { text: "Ladder quoted +6 min at 6:51 pm instead of pausing; headroom recovered by 7:20 pm", evidence: ["18:51", "19:20"] },
      { text: "Karaage feature at 3:10 pm filled an idle fryer: 11 extra orders at full margin", evidence: ["15:10–16:00", "+11 orders"] },
    ],
    wrong: [
      { text: "8 orders late, worst 14 min (DD-142)", evidence: ["DD-142", "18:21"] },
      { text: "Grubhub kept Gyoza live 9 min after the pause request", evidence: ["19:02–19:11"] },
      { text: "Forecast missed high by 14% between 7 and 8 pm", evidence: ["19:00–20:00", "P90 62 vs 71"] },
    ],
    causes: [
      { text: "Fryer slowdown 5:42–6:10 pm caused 6 of the 8 late orders", evidence: ["17:42–18:10", "6/8"] },
      { text: "Penguins game effect stronger than the knowledge base's 8% (measured 13%)", evidence: ["2026-10-08", "2026-10-22", date] },
    ],
    actions: [
      { id: `ai-${d}-1`, text: "Recount gyoza at 6:30 pm on game nights", owner: "Maya", check_on: "2026-11-12", measure: "No Gyoza 86 before 9 pm", status: "open" },
      { id: `ai-${d}-2`, text: "Ask the line to log fryer temperature at 5:30 pm", owner: "Kenji", check_on: "2026-11-10", measure: "Fryer incidents per week", status: "open" },
    ],
    kb_changes: [
      { id: "kb-0142", op: "update", statement: "Weekday Penguins home games raise delivery orders after puck drop", status: "active" },
      { id: "kb-0157", op: "add", statement: "Pause Gyoza on Grubhub 15 min earlier on game nights", status: "proposed" },
    ],
    digest_id: `day-${date}`,
  };
}
const KB: KbItem[] = [
  ["kb-0142", "event_effect", { weekday: "Thu", daypart: "dinner", event: "Penguins home game", channel: "delivery" }, "Weekday Penguins home games raise delivery orders after puck drop", { metric: "orders", change_pct: 8, window: "19:00-21:30" }, ["2026-10-08", "2026-10-22", "2026-11-05"], 0.7, "active", false],
  ["kb-0143", "event_effect", { weather: "rain", daypart: "dinner" }, "Rainy weekday dinners move orders from dine-in to delivery", { metric: "delivery_share", change_pct: 11 }, ["2026-09-18", "2026-10-02", "2026-10-15", "2026-10-30"], 0.82, "active", false],
  ["kb-0149", "capacity", { station: "fryer" }, "The fryer sustains 14 tickets per 15 min with two cooks; above that it backs up", { metric: "tickets_per_15", value: 14 }, ["2026-10-17", "2026-10-24", "2026-10-31"], 0.66, "active", false],
  ["kb-0150", "item_behavior", { item: "Gyoza", weekday: "Fri" }, "Gyoza sells out before 9 pm on Fridays above 230 orders", { metric: "runout", window: "20:15-20:55" }, ["2026-10-10", "2026-10-24", "2026-10-31"], 0.61, "active", false],
  ["kb-0151", "pricing", { item: "Karaage", daypart: "afternoon" }, "$1 off Karaage between 3 and 4 pm brings 9–12 extra orders when the fryer is idle", { metric: "orders", change_pct: 18 }, ["2026-10-21", "2026-10-28", "2026-11-04"], 0.58, "active", false],
  ["kb-0153", "ops_rule", { weekday: "Fri" }, "Recount gyoza at 6:30 pm on Fridays", null, ["2026-10-24", "2026-10-31"], 0.5, "proposed", true],
  ["kb-0155", "ops_rule", { event: "Penguins home game" }, "Quote delivery +5 min from puck drop on game nights instead of pausing items", { param: "ladder.quote_below", value: 5 }, ["2026-10-08", "2026-10-22", "2026-11-05"], 0.55, "proposed", true],
  ["kb-0156", "capacity", { station: "noodles" }, "Noodle station runs 12% slower when one cook covers noodles and packing", { metric: "speed", change_pct: -12 }, ["2026-10-30", "2026-11-03", "2026-11-04"], 0.6, "proposed", true],
  ["kb-0157", "ops_rule", { channel: "grubhub", item: "Gyoza" }, "Pause Gyoza on Grubhub 15 min earlier on game nights", { param: "pause_lead_min", value: 15 }, ["2026-11-05"], 0.4, "proposed", true],
  ["kb-0131", "event_effect", { event: "Pitt home football" }, "Pitt home football Saturdays lower dine-in 6%", { metric: "dine_in", change_pct: -6 }, ["2026-09-06", "2026-09-20", "2026-10-04"], 0.28, "retired", false],
  ["kb-0158", "action_item", { owner: "Maya" }, "Recount gyoza at 6:30 pm on game nights", null, ["2026-11-05"], 0.5, "active", false],
].map(([id, kind, scope, statement, effect, evidence, confidence, status, needs]) => ({
  id: id as string, kind: kind as string, scope: scope as Record<string, any>, statement: statement as string, effect: effect as Record<string, any> | null,
  evidence: evidence as string[], n: (evidence as string[]).length, confidence: confidence as number, status: status as string, created: (evidence as string[])[0],
  last_confirmed: (evidence as string[])[(evidence as string[]).length - 1], source: "review-agent", needs_approval: needs as boolean,
})).map((x) => (x.needs_approval && x.status === "proposed" && x.n >= 2 ? { ...x, status: "needs_approval" } : x));
const ACTIONS: ActionItem[] = [
  { id: "ai-1105-1", text: "Recount gyoza at 6:30 pm on game nights", owner: "Maya", created: "2026-11-05", check_on: "2026-11-12", measure: "No Gyoza 86 before 9 pm", status: "open" },
  { id: "ai-1105-2", text: "Log fryer temperature at 5:30 pm", owner: "Kenji", created: "2026-11-05", check_on: "2026-11-10", measure: "Fryer incidents per week", status: "open" },
  { id: "ai-1031-1", text: "Move one cook to packing from 6 to 8 pm on Fridays", owner: "Maya", created: "2026-10-31", check_on: "2026-11-07", measure: "Avg courier wait under 4 min", status: "open" },
  { id: "ai-1029-1", text: "Prep 20 more chashu on rainy Thursdays", owner: "Kenji", created: "2026-10-29", check_on: "2026-11-05", measure: "No chashu sell-out before 9 pm", status: "done", outcome: "Lasted to 9:40 pm on Nov 5" },
  { id: "ai-1024-1", text: "Quote +5 min on Grubhub instead of pausing at −10%", owner: "Gondola", created: "2026-10-24", check_on: "2026-10-31", measure: "Grubhub cancels per night", status: "not_working", outcome: "Cancels 4 → 5; reverting to pause" },
  { id: "ai-1022-1", text: "Feature Karaage 3–4 pm when the fryer is idle", owner: "Gondola", created: "2026-10-22", check_on: "2026-10-29", measure: "Afternoon orders", status: "done", outcome: "+11 orders per afternoon on average" },
];
function digests(kind: string, limit: number): Digest[] {
  const out: Digest[] = [];
  const base = new Date(`${todayIso}T12:00:00`);
  const n = kind === "day" ? Math.min(limit, 14) : kind === "week" ? Math.min(limit, 8) : Math.min(limit, 4);
  for (let i = 0; i < n; i++) {
    const d = new Date(base);
    if (kind === "day") d.setDate(d.getDate() - i - (nowFor(todayIso) < CLOSE + 30 ? 1 : 0));
    else if (kind === "week") d.setDate(d.getDate() - 7 * i - ((d.getDay() + 6) % 7));
    else d.setMonth(d.getMonth() - i - 1);
    const iso = `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
    const r = hash(`${kind}${iso}`);
    const period = kind === "month" ? iso.slice(0, 7) : iso;
    const orders = Math.round((kind === "day" ? 190 : kind === "week" ? 1380 : 5900) * (0.85 + r * 0.3));
    out.push({ id: `${kind}-${period}`, kind, period, numbers: { orders, promises_met: Math.round((0.86 + r * 0.1) * 100) / 100, worst_wait_min: Math.round(8 + r * 12), late: Math.round(r * 12), forecast_error_pct: Math.round(4 + r * 9) },
      summary: kind === "day" ? [r > 0.5 ? "Fryer backed up during the rush" : "Steady service, no sell-outs", `${Math.round(r * 12)} late orders`, r > 0.6 ? "Ladder quoted longer twice" : "Ladder stayed normal"]
        : kind === "week" ? ["Game nights ran 10–13% above forecast", "Gyoza ran out twice", "Courier waits down 1.2 min"] : ["Promises met up 4 points", "Two knowledge items retired", "Karaage afternoon feature kept"] });
  }
  return out;
}
function context(agent: string, date: string): ContextPayload {
  const st = presentState(date);
  const budget = { rush: 3000, outlook: 2000, exceptions: 2000, review: 6000 }[agent] || 2000;
  const kbFor = KB.filter((k) => k.status === "active" && (agent === "rush" ? ["capacity", "pricing", "ops_rule"].includes(k.kind) : agent === "outlook" ? k.kind === "event_effect" : agent === "exceptions" ? k.kind === "ops_rule" : true)).slice(0, agent === "review" ? 10 : agent === "rush" ? 5 : agent === "outlook" ? 8 : 3);
  const payload: Record<string, unknown> = agent === "rush"
    ? { state: { now: st.now, headroom_pct: st.headroom_pct, ladder: st.ladder.name, channels: st.channels }, queue_head: st.queue.slice(0, 6).map((q) => ({ order_id: q.order_id, channel: q.channel, slack_min: q.slack_min, status: q.status })), last_15_min: st.actions.slice(0, 4), shift_log: ["Fryer slow 5:42–6:10 pm", "Quoted +6 min at 6:51 pm"], knowledge: kbFor.map((k) => ({ id: k.id, statement: k.statement, confidence: k.confidence })) }
    : agent === "outlook" ? { calendar: BASE_DRIVERS(date).map((d) => d.label), weather: st.weather, knowledge: kbFor.map((k) => ({ id: k.id, statement: k.statement, effect: k.effect })), yesterday_error_pct: 6.4 }
      : agent === "exceptions" ? { trigger: exceptionsFor(date)[0] || null, related_orders: st.queue.slice(0, 3).map((q) => q.order_id), rules: kbFor.map((k) => k.statement) }
        : { day_inputs: pastSummary(date), last_7_wrong: ["Fryer backed up", "Gyoza ran out"], open_actions: ACTIONS.filter((a) => a.status === "open").map((a) => a.text), knowledge: kbFor.map((k) => ({ id: k.id, statement: k.statement })) };
  const tokens = Math.round(JSON.stringify(payload).length / 3.8);
  return { agent, date, tokens, budget_tokens: budget, payload, dropped: [] };
}

/* ---------------- router ---------------- */
export function triRequest(p: string, q: URLSearchParams, method: string, body: any, p50Of: (d: string) => number): unknown | undefined {
  const date = q.get("date") || body?.date || todayIso;
  const at = q.get("at");
  const minute = at === null ? undefined : Math.min(toMin(at), nowFor(date));
  if (p === "/past/summary") {
    const sum = pastSummary(date, minute);
    return at ? { ...sum, cutoff: at } : sum;
  }
  if (p === "/past/ledger") {
    const types = (q.get("types") || "").split(",").filter(Boolean);
    const before = Number(q.get("before_id") || 0);
    const limit = Number(q.get("limit") || 200);
    const all = ledgerEvents(date, minute).filter((e) => (!at || e.ts < `${date}T${at}:00`) && (!types.length || types.includes(e.type)) && (!before || e.id < before));
    const page = all.slice(0, limit);
    return { events: page, next_before_id: all.length > limit ? page[page.length - 1].id : null };
  }
  if (p === "/present/state") {
    const st = presentState(date, minute);
    const after = q.get("after");
    if (at && minute !== undefined && after) {
      st.playback_actions = actionsFor(date, minute).filter((a) => {
        const time = a.ts?.slice(11, 16) || a.time || "";
        return time >= after && time < at;
      }).reverse();
    }
    return at ? { ...st, phase: "replay" } : st;
  }
  if (p === "/present/compare") { const c = compareAt(date, nowFor(date)); return c; }
  if (p === "/present/settings") { if (method === "PUT") { Object.assign(settings.ladder, body.ladder || {}); Object.assign(settings.weights, body.weights || {}); if (body.max_wait_min) settings.max_wait_min = body.max_wait_min; } return JSON.parse(JSON.stringify(settings)); }
  if (p === "/present/simulate") {
    const st = presentState(date);
    const a = String(body?.action?.action || "");
    const gain = a === "busy" ? 22 : a === "pause_item" ? 11 : a === "quote" ? 6 : a === "promote" ? -9 : 0;
    const late = st.queue.filter((r) => (r.slack_min ?? 0) < 0).length;
    return { headroom_pct_before: st.headroom_pct, headroom_pct_after: Math.round((st.headroom_pct + gain) * 10) / 10, late_orders_before: late, late_orders_after: Math.max(0, late - Math.round(gain / 6)), notes: [gain > 0 ? "Frees capacity in the next 30 min" : "Uses spare capacity"] };
  }
  if (p === "/present/agent") {
    const st = presentState(date);
    const m = nowFor(date);
    const tight = st.headroom_pct < -5;
    const a: Action = { ts: `${date}T${hms(m)}`, action: tight ? "pause_item" : "offer", channel: tight ? "grubhub" : "doordash", item: tight ? "Gyoza" : "Karaage", value: tight ? null : 1,
      ladder_level: st.ladder.level, headroom_pct: st.headroom_pct, reason: tight ? "Fryer booked 22 min ahead and 3 Grubhub orders due in 10 min; pausing Gyoza on Grubhub frees 9 fryer-minutes" : "Fryer idle for 25 min; $1 off Karaage on DoorDash within budget and margin floor", by: "rush-agent",
      receipt_id: `rcpt-${Math.floor(hash(String(Date.now())) * 1e6)}` };
    agentActions.push(a);
    return { decision: tight ? "Pause Gyoza on Grubhub for 20 min" : "Feature Karaage on DoorDash", actions: [a], receipt: { receipt_id: a.receipt_id, model: "offline rules", checked: ["get_state", "get_queue", "simulate", "apply"], guard: "passed" } };
  }
  if (p === "/future/outlook") return { status: "fallback", active: false, target_date: date, reason: "Browser sample mode: no agent has run; showing the sample forecast." };
  if (p === "/future/today") return futureToday(date, minute);
  if (p === "/future/items") return { items: itemsAt(date, minute) };
  if (p === "/future/days") return futureDays(q.get("start") || todayIso, Number(q.get("n") || 7), { p50Of });
  if (p === "/review/exceptions") return exceptionsFor(date);
  if (p.startsWith("/review/exceptions/") && p.endsWith("/resolve")) { resolved.add(p.split("/")[3]); return { ok: true }; }
  if (p === "/review/scan") return exceptionsFor(date).filter((x) => !x.resolved).slice(0, 1);
  if (p.startsWith("/review/day/")) return dayReview(p.slice(12));
  if (p === "/review/run") return dayReview(date);
  if (p === "/review/kb") { const s = q.get("status"), k = q.get("kind"); return KB.filter((x) => (!s || s.split(",").includes(x.status)) && (!k || x.kind === k)); }
  if (p.startsWith("/review/kb/")) {
    const [, , , id, op] = p.split("/");
    const it = KB.find((x) => x.id === id); if (!it) throw new Error(`no item ${id}`);
    if (op === "approve") { it.status = "active"; it.needs_approval = false; } else if (op === "retire") it.status = "retired";
    return { ok: true, item: it };
  }
  if (p === "/review/actions") { const s = q.get("status"); return ACTIONS.filter((a) => !s || s.split(",").includes(a.status)); }
  if (p.startsWith("/review/actions/") && p.endsWith("/status")) { const a = ACTIONS.find((x) => x.id === p.split("/")[3]); if (!a) throw new Error("no action item"); a.status = body.status; a.outcome = body.note || (body.status === "done" ? "Marked done by the manager" : null); return { ok: true }; }
  if (p === "/review/digests") return digests(q.get("kind") || "day", Number(q.get("limit") || 30));
  if (p === "/review/context") return context(q.get("agent") || "rush", date);
  return undefined;
}

export function triStream(path: string, on: Handlers): (() => void) | undefined {
  if (path.startsWith("/present/stream")) return presentStream(new URLSearchParams(path.split("?")[1] || ""), on);
  return undefined;
}

export const sampleNow = () => { const m = sampleMin(); return { now: hms(m), phase: m < OPEN ? "before_open" : m > CLOSE ? "closed" : "open" }; };
