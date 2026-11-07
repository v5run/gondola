import { createContext, useCallback, useContext, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { stream } from "./api/client";
import { levelKey, normAction, normState, tri, sevRank, type Action, type ExceptionItem, type PresentState } from "./api/tri";
import { appName } from "./components/ui";
import { useApp, useToast } from "./state";
import { useAgents } from "./agents";

/* ================= Present: today's queue on the real clock ================= */

export interface PresentLive {
  /** Latest full state for today (SSE `state`, or a poll when the stream is unavailable). */
  state: PresentState | null;
  status: "idle" | "connecting" | "streaming" | "polling" | "error";
  error?: string;
  /** Wall-clock ms when `state` arrived: slack and the timeline advance from it between updates. */
  at: number;
  /** Order ids that arrived since the page opened (for the arrival highlight). */
  fresh: Set<string>;
  refresh: () => void;
  /** Local actions (agent runs, manual changes) shown before the next state arrives. */
  push: (a: Action) => void;
}
const PresentCtx = createContext<PresentLive>({ state: null, status: "idle", at: 0, fresh: new Set(), refresh: () => {}, push: () => {} });
export const usePresentLive = () => useContext(PresentCtx);

export const LEVEL_NAME: Record<string, string> = { promote: "Promote", normal: "Normal", quote: "Quote longer", pause_items: "Pause slow items", busy: "Busy mode" };
export const actionText = (a: Action) => {
  const who = a.channel ? appName[a.channel] || a.channel : "";
  switch (a.action) {
    case "ladder": return a.from ? `${LEVEL_NAME[levelKey(a.from)]} → ${LEVEL_NAME[levelKey(a.value)]}` : `Ladder: ${LEVEL_NAME[levelKey(a.value)]}`;
    case "quote": return `Quoting${who ? ` ${who}` : " delivery"} ${a.value ? `+${a.value} min` : "longer"}`;
    case "unpause_item": return `Resumed ${a.item || "items"}${who ? ` on ${who}` : ""}`;
    case "unbusy": return `${who || "App"} back open`;
    case "pause_item": return `Paused ${a.item || "slow items"}${who ? ` on ${who}` : ""}`;
    case "busy": return `Busy mode${who ? ` on ${who}` : ""}`;
    case "resume": return `Resumed${who ? ` ${who}` : " normal intake"}`;
    case "promote": return `Promoting ${a.item || "idle stations"}`;
    case "offer": return `Offer${a.item ? ` on ${a.item}` : ""}${who ? ` · ${who}` : ""}`;
    default: return `${a.action.replace(/_/g, " ").replace(/^./, (c) => c.toUpperCase())}${a.item ? ` ${a.item}` : ""}${who ? ` · ${who}` : ""}`;
  }
};
export const actor = (a: Action) => (a.by === "rush-agent" ? "rush" : a.action === "offer" || a.action === "promote" ? "pricing" : a.by === "manager" ? "controller" : "controller");

export function PresentProvider({ children }: { children: ReactNode }) {
  const { mode, now, inService, view } = useApp();
  const { pulse } = useAgents();
  const toast = useToast();
  const [state, setState] = useState<PresentState | null>(null);
  const [status, setStatus] = useState<PresentLive["status"]>("idle");
  const [error, setError] = useState<string>();
  const [at, setAt] = useState(0);
  const [gen, setGen] = useState(0);
  const fresh = useRef(new Set<string>());
  const local = useRef<Action[]>([]);
  const today = now?.today || "";
  const take = useCallback((s: PresentState) => {
    if (local.current.length) {
      const keep = local.current.filter((a) => !s.actions.some((b) => b.ts === a.ts && b.action === a.action));
      local.current = keep;
      s = { ...s, actions: [...keep, ...s.actions] };
    }
    setState(s); setAt(Date.now());
  }, []);

  useEffect(() => {
    if (!mode || !today || view === "playback") return;
    let dead = false;
    let poll: ReturnType<typeof setInterval> | undefined;
    let stop = () => {};
    const pollNow = () => tri.present.state(today).then((s) => { if (!dead) { take(s); setStatus("polling"); setError(undefined); } })
      .catch((e) => { if (!dead) { setStatus("error"); setError(String(e.message || e)); } });
    if (!inService) { setStatus("connecting"); pollNow(); return () => { dead = true; }; }
    setStatus("connecting");
    let got = false;
    stop = stream(`/present/stream?date=${today}`, {
      state: (s: PresentState) => { got = true; take(normState(s)); setStatus("streaming"); setError(undefined); },
      order: (o: { order_id: string; channel?: string; rank?: number | null; ts?: string }) => {
        fresh.current.add(o.order_id);
        pulse("ledger", `logged ${o.order_id}${o.channel ? ` from ${appName[o.channel] || o.channel}` : ""}`, o.ts);
        if (o.rank) pulse("controller", `ranked ${o.order_id} #${o.rank}`, o.ts);
      },
      action: (raw: Action) => {
        const a = normAction(raw, today);
        const who = actor(a);
        pulse(who, actionText(a).replace(/^./, (c) => c.toLowerCase()), a.ts?.slice(11, 16));
        toast(actionText(a), a.action === "busy" || a.action === "pause_item" ? "crit" : "info");
      },
      done: () => setStatus("idle"),
      error: () => {
        if (dead) return;
        // the stream isn't there (or dropped): poll every 15 s, and retry the stream in a minute
        stop();
        if (!poll) { pollNow(); poll = setInterval(pollNow, 15000); }
        setTimeout(() => { if (!dead) setGen((g) => g + 1); }, got ? 6000 : 60000);
      },
    });
    return () => { dead = true; stop(); if (poll) clearInterval(poll); };
  }, [mode, today, inService, view, gen, take, pulse, toast]);

  const v = useMemo<PresentLive>(() => ({
    state, status, error, at, fresh: fresh.current,
    refresh: () => setGen((g) => g + 1),
    push: (a: Action) => { local.current = [a, ...local.current]; setState((s) => (s ? { ...s, actions: [a, ...s.actions] } : s)); },
  }), [state, status, error, at]);
  return <PresentCtx.Provider value={v}>{children}</PresentCtx.Provider>;
}

/* ================= Review: exceptions during the day ================= */

interface ExCtx { list: ExceptionItem[] | null; open: number; error?: string; reload: () => void; resolveLocal: (id: string) => void }
const ExceptionsCtx = createContext<ExCtx>({ list: null, open: 0, reload: () => {}, resolveLocal: () => {} });
export const useExceptions = () => useContext(ExceptionsCtx);

/** Polls today's exceptions every 20 s; new ones light the Exceptions agent, high ones also raise a toast. */
export function ExceptionsProvider({ children }: { children: ReactNode }) {
  const { mode, now, view } = useApp();
  const { pulse } = useAgents();
  const toast = useToast();
  const [list, setList] = useState<ExceptionItem[] | null>(null);
  const [error, setError] = useState<string>();
  const [n, setN] = useState(0);
  const seen = useRef<Set<string> | null>(null);
  const today = now?.today || "";
  useEffect(() => {
    if (!mode || !today || view === "playback") return;
    let dead = false;
    const pull = () => tri.review.exceptions(today).then((l) => {
      if (dead) return;
      setList(l); setError(undefined);
      if (seen.current) {
        for (const x of l) if (!seen.current.has(x.id)) {
          pulse("exceptions", `${x.decision === "alert" ? "alerted" : x.decision === "present" ? "handed to Present" : "noted"}: ${x.title.replace(/^./, (c) => c.toLowerCase())}`, x.ts.slice(11, 16));
          if (x.decision === "alert") pulse("sentinel", "texted the manager", x.ts.slice(11, 16));
          if (sevRank(x.severity) === 0) toast(x.title, "crit");
        }
      }
      seen.current = new Set(l.map((x) => x.id));
    }).catch((e) => { if (!dead) setError(String(e.message || e)); });
    pull();
    const id = setInterval(pull, 20000);
    return () => { dead = true; clearInterval(id); };
  }, [mode, today, view, n, pulse, toast]);
  const v = useMemo<ExCtx>(() => ({
    list, error, open: (list || []).filter((x) => !x.resolved).length, reload: () => setN((x) => x + 1),
    resolveLocal: (id) => setList((l) => (l ? l.map((x) => (x.id === id ? { ...x, resolved: true } : x)) : l)),
  }), [list, error]);
  return <ExceptionsCtx.Provider value={v}>{children}</ExceptionsCtx.Provider>;
}
