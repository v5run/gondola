import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, apiMode, stream } from "./api/client";
import type { Integrations, LiveEvent, LiveOrder, LiveTick, NowInfo, Store } from "./api/types";
import { addDays, clampDate } from "./lib/dates";
import { shortEvent } from "./lib/events";
import { useAgents } from "./agents";

/* ================= app: store, mode, global date, view, store clock ================= */

export type View = "live" | "day";
interface AppCtx {
  store: Store | null; integrations: Integrations | null; mode: "live" | "mock" | null;
  date: string; setDate: (d: string) => void; step: (n: number) => void; today: () => void;
  view: View; setView: (v: View) => void;
  /** The store clock (GET /api/now), refreshed every minute. "Today" is now.today; nothing after it exists. */
  now: NowInfo | null;
  /** True while today is in service (or about to open): the live stream runs on the real clock. */
  inService: boolean;
}
const App = createContext<AppCtx>(null as unknown as AppCtx);
export const useApp = () => useContext(App);
/** Replay speeds for the Service (Guard) replay; the dashboard itself runs on the real clock. */
export const SPEEDS: [number, string][] = [[60, "1 min/s"], [300, "5 min/s"], [600, "10 min/s"], [1800, "30 min/s"]];

/* the ticking real time, in its own context so only the clock readouts re-render every second */
const ClockCtx = createContext<string | null>(null);
/** "HH:MM:SS" on the store clock, ticking every second (null until /api/now answers). */
export const useClock = () => useContext(ClockCtx);
const secOf = (t: string) => { const [h, m, s] = t.split(":").map(Number); return h * 3600 + m * 60 + (s || 0); };
const hms = (x: number) => { x = ((Math.floor(x) % 86400) + 86400) % 86400; return [x / 3600, (x % 3600) / 60, x % 60].map((v) => String(Math.floor(v)).padStart(2, "0")).join(":"); };

export function AppProvider({ children }: { children: ReactNode }) {
  const [store, setStore] = useState<Store | null>(null);
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [mode, setMode] = useState<"live" | "mock" | null>(null);
  const [date, setDateRaw] = useState("");
  const [view, setView] = useState<View>("live");
  const [now, setNow] = useState<NowInfo | null>(null);
  const [tick, setTick] = useState<string | null>(null);
  const got = useRef(0);
  useEffect(() => {
    apiMode().then((m) => {
      setMode(m);
      api.integrations().then(setIntegrations).catch(() => {});
    });
  }, []);
  // the clock: ask the server every minute, tick locally in between
  useEffect(() => {
    let dead = false;
    const pull = () => api.now().then((n) => { if (!dead) { got.current = Date.now(); setNow(n); } }).catch(() => {});
    pull();
    const id = setInterval(pull, 60000);
    return () => { dead = true; clearInterval(id); };
  }, []);
  useEffect(() => {
    if (!now) return;
    const at = () => setTick(hms(secOf(now.now) + (Date.now() - got.current) / 1000));
    at();
    const id = setInterval(at, 1000);
    return () => clearInterval(id);
  }, [now]);
  // the store (its "today") follows the clock: a new business day at 4 a.m. moves today forward
  const prevToday = useRef("");
  useEffect(() => {
    if (!now || now.today === prevToday.current) return;
    const wasToday = prevToday.current;
    prevToday.current = now.today;
    api.store().then((s) => { setStore(s); setDateRaw((d) => (!d || d === wasToday ? s.today : d)); }).catch(() => {});
  }, [now]);
  const lo = store?.first_date, hi = store?.today;
  const setDate = useCallback((d: string) => setDateRaw(clampDate(d, lo, hi)), [lo, hi]);
  const step = useCallback((n: number) => setDateRaw((d) => clampDate(addDays(d, n), lo, hi)), [lo, hi]);
  const today = useCallback(() => hi && setDateRaw(hi), [hi]);
  // ←/→ step the global date anywhere outside text fields and sliders (→ stops at today)
  useEffect(() => {
    const k = (e: KeyboardEvent) => {
      if (e.metaKey || e.ctrlKey || e.altKey || (e.key !== "ArrowLeft" && e.key !== "ArrowRight")) return;
      const t = e.target as HTMLElement;
      if (t.closest("input, textarea, select, [contenteditable], [role=slider], [data-keys]")) return;
      e.preventDefault();
      step((e.key === "ArrowLeft" ? -1 : 1) * (e.shiftKey ? 7 : 1));
    };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [step]);
  const inService = !!now && now.phase !== "closed";
  const v = useMemo(() => ({ store, integrations, mode, date, setDate, step, today, view, setView, now, inService }),
    [store, integrations, mode, date, setDate, step, today, view, now, inService]);
  return <App.Provider value={v}><ClockCtx.Provider value={tick}>{children}</ClockCtx.Provider></App.Provider>;
}

/* ================= toasts ================= */

interface Toast { id: number; text: string; tone?: "crit" | "good" | "info" }
const ToastCtx = createContext<(text: string, tone?: Toast["tone"]) => void>(() => {});
export const useToast = () => useContext(ToastCtx);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [list, setList] = useState<Toast[]>([]);
  const n = useRef(0);
  const push = useCallback((text: string, tone?: Toast["tone"]) => {
    const id = ++n.current;
    setList((l) => [...l.slice(-3), { id, text, tone }]);
    setTimeout(() => setList((l) => l.filter((t) => t.id !== id)), 3600);
  }, []);
  return (
    <ToastCtx.Provider value={push}>
      {children}
      {createPortal(
        <div className="toasts" aria-live="polite">
          {list.map((t) => <div key={t.id} className={`toast ${t.tone || ""}`}><i className="dot" />{t.text}</div>)}
        </div>, document.body)}
    </ToastCtx.Provider>
  );
}

/* ================= live service: today on the real clock ================= */

export interface LiveState {
  status: "idle" | "connecting" | "running" | "done" | "error";
  /** the date the feed is for, its orders and events so far (catch-up included), Chashu prepped */
  date: string; orders: LiveOrder[]; events: LiveEvent[]; par: number | null; error?: string;
  /** running totals of everything placed so far, from the order feed (updates per order) */
  cur: LiveTick | null;
  restart: () => void;
}
const LiveCtx = createContext<LiveState>(null as unknown as LiveState);
export const useLive = () => useContext(LiveCtx);

function totals(orders: LiveOrder[], par: number): LiveTick {
  const by = { in_store: 0, doordash: 0, ubereats: 0, grubhub: 0 };
  const sales = { in_store: 0, doordash: 0, ubereats: 0, grubhub: 0 };
  let n = 0, net = 0, cancels = 0, used = 0;
  for (const o of orders) {
    if (o.status === "completed") { n++; net += o.subtotal; by[o.channel]++; sales[o.channel] += o.subtotal; used += o.chashu || 0; }
    else if (/cancel/.test(o.status)) cancels++;
  }
  return { t: orders.length ? orders[orders.length - 1].t : "", orders: n, placed: orders.length, net_sales: net, by_channel: by,
    by_channel_sales: sales, chashu_left: Math.max(0, par - used), cancels };
}

/** While today is in service, Tonight joins the day on the real clock: one stream that first sends the day so far
 *  (catch-up), then each order and event at its own time (speed 1). Toasts only for events as they happen. */
export function LiveProvider({ children }: { children: ReactNode }) {
  const { date, view, mode, now, inService } = useApp();
  const clockNow = useClock();
  const toast = useToast();
  const { pulse } = useAgents();
  const [status, setStatus] = useState<LiveState["status"]>("idle");
  const [error, setError] = useState<string>();
  const [, force] = useState(0);
  const buf = useRef({ date: "", orders: [] as LiveOrder[], events: [] as LiveEvent[], ids: new Set<string>(), par: null as number | null });
  const [gen, setGen] = useState(0);
  const raf = useRef(0);
  const clockRef = useRef(clockNow);
  clockRef.current = clockNow;
  const flush = useCallback(() => {
    if (raf.current) return;
    raf.current = requestAnimationFrame(() => { raf.current = 0; force((x) => x + 1); });
  }, []);
  const active = view === "live" && !!mode && !!now && inService && date === now.today;
  const ready = active && !!clockRef.current;

  useEffect(() => {
    if (!ready) { setStatus("idle"); return; }
    if (buf.current.date !== date) buf.current = { date, orders: [], events: [], ids: new Set(), par: null };
    setStatus("connecting"); setError(undefined); flush();
    let retry: ReturnType<typeof setTimeout> | undefined;
    const from = clockRef.current as string;
    const stop = stream(`/live/stream?date=${date}&speed=1&from=${from}&catchup=1`, {
      start: (s: { par?: number }) => { buf.current.par = typeof s.par === "number" ? s.par : null; setStatus("running"); flush(); },
      order: (o: LiveOrder) => {
        const B = buf.current;
        if (B.ids.has(o.id)) return;
        B.ids.add(o.id); B.orders.push(o);
        if (B.orders.length > 1 && o.t < B.orders[B.orders.length - 2].t) B.orders.sort((a, b) => a.t.localeCompare(b.t));
        flush();
      },
      event: (e: LiveEvent) => {
        const B = buf.current;
        if (B.events.some((x) => x.t === e.t && x.text === e.text)) return;
        B.events.push(e); flush();
        if (e.catchup) return; // the day so far: shown in the cards, not toasted
        toast(shortEvent(e), e.kind === "sold_out" || e.kind === "pause" ? "crit" : "info");
        const txt = shortEvent(e).replace(/^Chashu paused on/, "paused chashu on");
        if (e.kind === "pause" || e.kind === "sold_out") pulse("guard", txt, e.t);
        if (e.kind === "sold_out") pulse("sentinel", "flagged the sell-out", e.t);
        if (e.kind === "rush_start" || e.kind === "rush_end") pulse("demand", e.kind === "rush_start" ? "rush started" : "rush over", e.t);
      },
      done: () => { setStatus("done"); flush(); },
      error: (e: { message: string }) => {
        setStatus("error"); setError(e.message);
        retry = setTimeout(() => setGen((g) => g + 1), 6000); // reconnect from the current time; ids dedupe the catch-up
      },
    });
    return () => { stop(); if (retry) clearTimeout(retry); };
  }, [date, ready, gen, flush, toast, pulse]);

  const b = buf.current;
  const n = b.orders.length;
  const cur = useMemo(() => (b.date && (n || b.par !== null) ? totals(b.orders, b.par ?? 0) : null), [b.date, n, b.par]); // eslint-disable-line
  const st = active ? status : "idle";
  const value = useMemo<LiveState>(() => ({
    status: st, error, date: b.date, orders: b.orders, events: b.events, par: b.par, cur,
    restart: () => { buf.current = { date: "", orders: [], events: [], ids: new Set(), par: null }; setGen((g) => g + 1); },
  }), [st, error, b.date, n, b.events.length, b.par, cur]); // eslint-disable-line
  return <LiveCtx.Provider value={value}>{children}</LiveCtx.Provider>;
}
