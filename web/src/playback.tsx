import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { useLocation } from "react-router-dom";
import { useAgents } from "./agents";
import { api } from "./api/client";
import { normAction, tri, type FutureToday, type LimitedItem, type PastSummary, type PresentState } from "./api/tri";
import type { Intraday } from "./api/types";
import { D, fromMin, toMin } from "./lib/dates";
import { actionText, actor } from "./live";
import { useApp, useClearToasts, useToast } from "./state";

const SPEEDS = [0.2, 0.5, 1, 2, 5, 10, 30];
export const speedLabel = (s: number) => (s < 1 ? `1 min every ${Math.round(1 / s)} s` : `${s} min/s`);
const OPEN = 11 * 60;
interface Frame {
  date: string;
  minute: number;
  present: PresentState;
  forecast: FutureToday;
  items: LimitedItem[];
  summary?: PastSummary;
  intraday?: Intraday;
}
interface PastPreview {
  date: string;
  minute: number;
  summary: PastSummary;
  intraday: Intraday;
}
interface Playback {
  active: boolean;
  playing: boolean;
  speed: number;
  minute: number;
  target: number;
  start: number;
  min: number;
  max: number;
  close: number;
  at: string;
  busy: boolean;
  error?: string;
  frame: Frame | null;
  pastPreview: PastPreview | null;
  toggle: () => void;
  seek: (minute: number) => void;
  setStart: (minute: number) => void;
  setSpeed: (speed: number) => void;
  retry: () => void;
}
const PlaybackContext = createContext<Playback>(null as unknown as Playback);
export const usePlayback = () => useContext(PlaybackContext);

export function PlaybackProvider({ children }: { children: ReactNode }) {
  const { view, date, now } = useApp();
  const { pathname } = useLocation();
  const { pulse, clearActivity } = useAgents();
  const toast = useToast();
  const clearToasts = useClearToasts();
  const active = view === "playback";
  const past = pathname === "/past";
  const compare = pathname === "/present";
  const weekday = date ? D(date).getDay() : 0;
  const close = date === now?.today ? toMin(now.close) : (weekday === 5 || weekday === 6 ? 23 : 22) * 60;
  const max = date === now?.today && now.cutoff ? Math.min(close, Math.floor(toMin(now.cutoff))) : close;
  const min = Math.min(OPEN, max);
  const [cursor, setCursor] = useState<{ date: string; minute: number; advancing: boolean }>({ date: "", minute: OPEN, advancing: false });
  const [start, setStart] = useState(OPEN);
  const [speed, setSpeed] = useState(0.5);
  const [playing, setPlaying] = useState(false);
  const [frame, setFrame] = useState<Frame | null>(null);
  const [pastPreview, setPastPreview] = useState<PastPreview | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string>();
  const [attempt, retry] = useState(0);
  const previous = useRef<Frame | null>(null);
  const wasActive = useRef(false);
  const anchor = useRef({ time: 0, minute: OPEN });
  const lastAdvance = useRef(0);
  const minute = Math.min(max, Math.max(min, cursor.date === date ? cursor.minute : start));
  const at = fromMin(minute);
  const visible = active && frame?.date === date ? frame : null;
  const shownMinute = visible?.minute ?? minute;

  useEffect(() => {
    if (active || wasActive.current) {
      clearActivity();
      clearToasts();
    }
    wasActive.current = active;
    setPlaying(false);
    previous.current = null;
    setFrame(null);
    setPastPreview(null);
    setError(undefined);
    setCursor({ date, minute: start, advancing: false });
    // The chosen start time carries across dates.
  }, [active, date]); // eslint-disable-line react-hooks/exhaustive-deps

  useEffect(() => {
    if (!active || !date || !now) return;
    let cancelled = false;
    const prior = cursor.advancing && previous.current?.date === date && previous.current.minute < minute ? previous.current : null;
    setBusy(true);
    setError(undefined);
    const load = async () => {
      const pastData = past ? Promise.all([tri.past.summary(date, at), api.intraday(date, at)])
        .then(([summary, intraday]) => {
          const data = { date, minute, summary, intraday };
          if (!cancelled && !previous.current) setPastPreview(data);
          return data;
        }) : undefined;
      return Promise.all([
        tri.present.state(date, at, prior ? fromMin(prior.minute) : undefined, compare),
        tri.future.today(date, at),
        tri.future.items(date, at),
        pastData,
      ]);
    };
    const commit = () => load().then(([present, forecast, stock, pastData]) => {
      if (cancelled) return;
      const next = { date, minute, present, forecast, items: stock.items, summary: pastData?.summary, intraday: pastData?.intraday };
      previous.current = next;
      setFrame(next);
      setBusy(false);
      if (!prior) return;
      const arrivals = forecast.so_far.orders - prior.forecast.so_far.orders;
      if (arrivals > 0) pulse("ledger", `logged ${arrivals} new order${arrivals === 1 ? "" : "s"}`, at);
      const ranks = new Map(prior.present.queue.map((o) => [o.order_id, o.rank]));
      if (present.queue.some((o) => ranks.get(o.order_id) !== o.rank)) pulse("controller", "updated queue ranks", at);
      if (Math.floor(prior.minute / 15) !== Math.floor(minute / 15)) pulse("forecaster", "updated the forecast", at);
      for (const raw of present.playback_actions || []) {
        const a = normAction(raw, date);
        const label = actionText(a);
        pulse(actor(a), label, a.ts?.slice(11, 16));
        toast(label, a.action === "busy" || a.action === "pause_item" ? "crit" : "info");
      }
      for (const item of stock.items) {
        if (item.believed_left > 0 || !prior.items.some((i) => i.key === item.key && i.believed_left > 0)) continue;
        const label = `${item.name} sold out`;
        toast(label, "crit");
        pulse("sentinel", label, at);
      }
    }).catch((e: Error) => {
      if (cancelled) return;
      setBusy(false);
      setPlaying(false);
      setError(e.message);
    });
    if (cursor.advancing) {
      commit();
      return () => { cancelled = true; };
    }
    const timer = window.setTimeout(commit, previous.current ? 100 : 0);
    return () => { cancelled = true; window.clearTimeout(timer); };
  }, [active, date, !!now, at, minute, cursor.advancing, past, compare, attempt, pulse, toast]);

  useEffect(() => {
    if (!active || !playing || visible?.minute !== minute || busy || error) return;
    if (minute >= max) { setPlaying(false); return; }
    const interval = 1000 / Math.min(speed, 5);
    const timer = window.setTimeout(() => {
      lastAdvance.current = performance.now();
      const next = Math.min(max, anchor.current.minute + Math.floor((performance.now() - anchor.current.time) * speed / 1000));
      setCursor({ date, minute: Math.max(minute + 1, next), advancing: true });
    }, Math.max(0, lastAdvance.current + interval - performance.now()));
    return () => window.clearTimeout(timer);
  }, [active, playing, visible, busy, error, minute, max, date, speed]);

  const seek = (m: number) => {
    clearActivity();
    clearToasts();
    setPlaying(false);
    setCursor({ date, minute: Math.min(max, Math.max(min, m)), advancing: false });
  };
  const toggle = () => {
    if (playing) {
      setPlaying(false);
      if (visible && visible.minute !== minute) {
        setCursor({ date, minute: visible.minute, advancing: false });
      }
      return;
    }
    if (max <= min || error || visible?.minute !== minute) return;
    const from = minute >= max ? Math.min(start, max) : minute;
    if (from >= max) return;
    lastAdvance.current = performance.now();
    anchor.current = { time: lastAdvance.current, minute: from };
    if (from !== minute) seek(from);
    setPlaying(true);
  };
  const changeSpeed = (n: number) => {
    lastAdvance.current = performance.now();
    anchor.current = { time: lastAdvance.current, minute: shownMinute };
    setSpeed(n);
  };

  const keys = useRef({ toggle, changeSpeed });
  keys.current = { toggle, changeSpeed };
  useEffect(() => {
    if (!active) return;
    const key = (e: KeyboardEvent) => {
      if (e.repeat || e.altKey || e.ctrlKey || e.metaKey || e.defaultPrevented) return;
      const target = e.target as HTMLElement;
      if (target.closest("input, textarea, select, [contenteditable], [role=slider], [data-keys]")) return;
      if (e.key === " " && !target.closest("button:not([role=radio]), a, [role=button]")) {
        e.preventDefault();
        keys.current.toggle();
      } else if (e.key === "[" || e.key === "]") {
        e.preventDefault();
        const i = SPEEDS.indexOf(speed) + (e.key === "[" ? -1 : 1);
        keys.current.changeSpeed(SPEEDS[Math.min(SPEEDS.length - 1, Math.max(0, i))]);
      }
    };
    window.addEventListener("keydown", key);
    return () => window.removeEventListener("keydown", key);
  }, [active, speed]);

  return <PlaybackContext.Provider value={{
    active, playing, speed, minute: shownMinute, target: minute, start, min, max, close, at: fromMin(shownMinute), busy, error, frame: visible, toggle, seek,
    pastPreview: active && !visible && pastPreview?.date === date && pastPreview.minute === minute ? pastPreview : null,
    setStart: (m) => { setStart(m); seek(m); },
    setSpeed: changeSpeed,
    retry: () => retry((n) => n + 1),
  }}>{children}</PlaybackContext.Provider>;
}

export function PlaybackControls() {
  const p = usePlayback();
  if (!p.active) return null;
  const seeking = p.busy && (!p.playing || !p.frame);
  const thumb = p.playing ? p.minute : p.target;
  return <div className="playback-controls" role="group" aria-label="Playback controls">
    <button className="btn small" onClick={p.toggle} disabled={!p.playing && (!p.frame || p.frame.minute !== p.target || p.min === p.max || !!p.error)}>{p.playing ? "Pause" : "Play"}</button>
    <label>Speed <select className="input slim" value={p.speed} onChange={(e) => p.setSpeed(Number(e.target.value))}>
      {SPEEDS.map((s) => <option key={s} value={s}>{speedLabel(s)}</option>)}
    </select></label>
    <label>Start time <input className="input slim" type="time" min={fromMin(p.min)} max={fromMin(p.max)}
      value={fromMin(Math.min(p.start, p.max))} onChange={(e) => {
        if (e.currentTarget.value) p.setStart(Math.min(p.max, Math.max(p.min, toMin(e.currentTarget.value))));
      }} /></label>
    <label className="playback-timeline">Timeline <input type="range" min={p.min} max={p.max} value={thumb}
      aria-valuetext={fromMin(thumb)} onChange={(e) => p.seek(Number(e.target.value))} disabled={p.min === p.max} /></label>
    <span className="playback-status muted" role="status">{seeking ? `Loading ${fromMin(p.target)}…` : ""}</span>
    {p.error && <span role="alert">{p.error} <button className="link" onClick={p.retry}>Retry</button></span>}
  </div>;
}
