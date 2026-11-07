import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { api, apiMode, stream } from "./api/client";
import type { Integrations, LiveEvent, LiveOrder, LiveTick, Store } from "./api/types";
import { addDays, clampDate, toMin } from "./lib/dates";
import { shortEvent } from "./lib/events";
import { useAgents } from "./agents";

/* ================= app: store, mode, global date, view ================= */

export type View = "live" | "day";
interface AppCtx {
  store: Store | null; integrations: Integrations | null; mode: "live" | "mock" | null;
  date: string; setDate: (d: string) => void; step: (n: number) => void; today: () => void;
  view: View; setView: (v: View) => void; speed: number; setSpeed: (n: number) => void;
}
const App = createContext<AppCtx>(null as unknown as AppCtx);
export const useApp = () => useContext(App);
export const SPEEDS: [number, string][] = [[60, "1 min/s"], [300, "5 min/s"], [600, "10 min/s"], [1800, "30 min/s"]];

export function AppProvider({ children }: { children: ReactNode }) {
  const [store, setStore] = useState<Store | null>(null);
  const [integrations, setIntegrations] = useState<Integrations | null>(null);
  const [mode, setMode] = useState<"live" | "mock" | null>(null);
  const [date, setDateRaw] = useState("");
  const [view, setView] = useState<View>("live");
  const [speed, setSpeed] = useState(600);
  useEffect(() => {
    apiMode().then((m) => {
      setMode(m);
      api.store().then((s) => { setStore(s); setDateRaw((d) => d || s.today); }).catch(() => {});
      api.integrations().then(setIntegrations).catch(() => {});
    });
  }, []);
  const lo = store?.first_date, hi = store?.today;
  const setDate = useCallback((d: string) => setDateRaw(clampDate(d, lo, hi)), [lo, hi]);
  const step = useCallback((n: number) => setDateRaw((d) => clampDate(addDays(d, n), lo, hi)), [lo, hi]);
  const today = useCallback(() => hi && setDateRaw(hi), [hi]);
  // ←/→ step the global date anywhere outside text fields and sliders
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
  const v = useMemo(() => ({ store, integrations, mode, date, setDate, step, today, view, setView, speed, setSpeed }),
    [store, integrations, mode, date, setDate, step, today, view, speed]);
  return <App.Provider value={v}>{children}</App.Provider>;
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

/* ================= live service stream ================= */

export interface LiveState {
  status: "idle" | "connecting" | "running" | "done" | "error";
  date: string; ticks: LiveTick[]; orders: LiveOrder[]; events: LiveEvent[]; error?: string;
  clock: string | null; restart: () => void;
}
const LiveCtx = createContext<LiveState>(null as unknown as LiveState);
export const useLive = () => useContext(LiveCtx);

export function LiveProvider({ children }: { children: ReactNode }) {
  const { date, view, speed, mode } = useApp();
  const toast = useToast();
  const { pulse } = useAgents();
  const [status, setStatus] = useState<LiveState["status"]>("idle");
  const [error, setError] = useState<string>();
  const [, force] = useState(0);
  const buf = useRef({ date: "", ticks: [] as LiveTick[], orders: [] as LiveOrder[], events: [] as LiveEvent[], ids: new Set<string>() });
  const [gen, setGen] = useState(0);
  const raf = useRef(0);
  const flush = useCallback(() => {
    if (raf.current) return;
    raf.current = requestAnimationFrame(() => { raf.current = 0; force((x) => x + 1); });
  }, []);
  const statusRef = useRef(status);
  statusRef.current = status;

  useEffect(() => {
    if (view !== "live" || !date || !mode) { setStatus("idle"); return; }
    const b = buf.current;
    // a new day, or a replay after the end, starts over from opening; a speed change resumes where it was
    let from = "11:00";
    if (b.date !== date || statusRef.current === "done" || !b.ticks.length) {
      buf.current = { date, ticks: [], orders: [], events: [], ids: new Set() };
    } else from = b.ticks[b.ticks.length - 1].t.slice(0, 5);
    setStatus("connecting"); setError(undefined); flush();
    let retry: ReturnType<typeof setTimeout> | undefined;
    let fresh = true;
    const stop = stream(`/live/stream?date=${date}&speed=${speed}&from=${from}`, {
      order: (o: LiveOrder) => {
        const B = buf.current;
        if (B.ids.has(o.id)) return;
        B.ids.add(o.id); B.orders.push(o); flush();
      },
      tick: (t: LiveTick) => {
        const B = buf.current;
        if (fresh) { setStatus("running"); fresh = false; }
        const last = B.ticks[B.ticks.length - 1];
        if (last && toMin(t.t) <= toMin(last.t)) return;
        B.ticks.push(t); flush();
      },
      event: (e: LiveEvent) => {
        const B = buf.current;
        if (B.events.some((x) => x.t === e.t && x.text === e.text)) return;
        B.events.push(e); flush();
        toast(shortEvent(e), e.kind === "sold_out" || e.kind === "pause" ? "crit" : "info");
        const txt = shortEvent(e).replace(/^Chashu paused on/, "paused chashu on");
        if (e.kind === "pause" || e.kind === "sold_out") pulse("guard", txt.toLowerCase().startsWith("paused") ? txt : txt, e.t);
        if (e.kind === "sold_out") pulse("sentinel", "flagged the sell-out", e.t);
        if (e.kind === "rush_start" || e.kind === "rush_end") pulse("demand", e.kind === "rush_start" ? "rush started" : "rush over", e.t);
      },
      done: () => { setStatus("done"); flush(); },
      error: (e: { message: string }) => {
        setStatus("error"); setError(e.message);
        retry = setTimeout(() => setGen((g) => g + 1), 6000); // the stream may not be deployed yet; keep trying
      },
    });
    return () => { stop(); if (retry) clearTimeout(retry); };
  }, [date, view, speed, mode, gen, flush, toast, pulse]);

  const b = buf.current;
  const last = b.ticks[b.ticks.length - 1];
  const value: LiveState = {
    status, error, date: b.date, ticks: b.ticks, orders: b.orders, events: b.events, clock: last ? last.t : null,
    restart: () => { buf.current = { date: "", ticks: [], orders: [], events: [], ids: new Set() }; setGen((g) => g + 1); },
  };
  return <LiveCtx.Provider value={value}>{children}</LiveCtx.Provider>;
}

