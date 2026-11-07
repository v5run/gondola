import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { clock } from "./components/ui";

/** The nine agents, in close-graph order. Marks are two letters so Stock and Sentinel stay distinct. */
export const AGENTS = [
  ["coordinator", "Co", "Coordinator", "Runs the close"],
  ["books", "Bk", "Books", "Checks cash, payouts and disputes"],
  ["stock", "St", "Stock", "Counts what's left"],
  ["demand", "Dm", "Demand", "Forecasts tomorrow"],
  ["analyst", "An", "Analyst", "Explains the day"],
  ["plan", "Pl", "Plan", "Sizes prep and pause times"],
  ["sentinel", "Sn", "Sentinel", "Decides who to text"],
  ["report", "Rp", "Report", "Writes the report"],
  ["guard", "Gd", "Guard", "Pauses apps before sell-outs"],
] as const;
export type AgentKey = (typeof AGENTS)[number][0];
const MARK = Object.fromEntries(AGENTS.map(([k, m]) => [k, m])) as Record<AgentKey, string>;

interface Act { text: string; t?: string }
interface Ctx {
  pulse: (a: string, text: string, t?: string) => void;
  setRunning: (a: string, on: boolean) => void;
  last: Record<string, Act>; running: Set<string>; flash: Record<string, number>;
}
const AgentCtx = createContext<Ctx>({ pulse: () => {}, setRunning: () => {}, last: {}, running: new Set(), flash: {} });
export const useAgents = () => useContext(AgentCtx);

const setHl = (a: string | null) => { if (a) document.body.dataset.hl = a; else delete document.body.dataset.hl; };

export function AgentProvider({ children }: { children: ReactNode }) {
  const [last, setLast] = useState<Record<string, Act>>({});
  const [running, setRun] = useState<Set<string>>(new Set());
  const [flash, setFlash] = useState<Record<string, number>>({});
  const pulse = useCallback((a: string, text: string, t?: string) => {
    if (!MARK[a as AgentKey]) return;
    setLast((l) => ({ ...l, [a]: { text, t } }));
    setFlash((f) => ({ ...f, [a]: (f[a] || 0) + 1 }));
  }, []);
  const setRunning = useCallback((a: string, on: boolean) => {
    setRun((s) => { if (s.has(a) === on) return s; const n = new Set(s); if (on) n.add(a); else n.delete(a); return n; });
  }, []);
  const v = useMemo(() => ({ pulse, setRunning, last, running, flash }), [pulse, setRunning, last, running, flash]);
  return <AgentCtx.Provider value={v}>{children}</AgentCtx.Provider>;
}

/** Slim column of agent marks for the sidebar foot. Each lights when its agent acts. */
export function AgentRail() {
  const { last, running, flash } = useAgents();
  return (
    <div className="rail" role="list" aria-label="Agents">
      {AGENTS.map(([k, m, name, job]) => <Glyph key={k} k={k} m={m} name={name} job={job} act={last[k]} on={running.has(k)} n={flash[k] || 0} />)}
    </div>
  );
}

function Glyph({ k, m, name, job, act, on, n }: { k: string; m: string; name: string; job: string; act?: Act; on: boolean; n: number }) {
  const [blink, setBlink] = useState(false);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    setBlink(true); const t = setTimeout(() => setBlink(false), 900); return () => clearTimeout(t);
  }, [n]);
  return (
    <div role="listitem" className={`ag${on ? " run" : ""}${blink ? " blink" : ""}`} data-agent={k} data-last={act?.text || ""} tabIndex={0}
      onMouseEnter={() => setHl(k)} onMouseLeave={() => setHl(null)} onFocus={() => setHl(k)} onBlur={() => setHl(null)} aria-label={name}>
      {m}
      <span className="tip">{name} · {act ? `${act.text}${act.t ? ` · ${clock(act.t)}` : ""}` : job}</span>
    </div>
  );
}

/** Tiny owner mark: drop inside any card; the card becomes that agent's (ring on rail hover). */
export function Own({ a, dark }: { a: AgentKey; dark?: boolean }) {
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const p = ref.current?.parentElement;
    if (p) p.dataset.owner = a;
    return () => { if (p && p.dataset.owner === a) delete p.dataset.owner; };
  }, [a]);
  return <i ref={ref} className={`og${dark ? " dark" : ""}`} aria-hidden="true" onMouseEnter={() => setHl(a)} onMouseLeave={() => setHl(null)}>{MARK[a]}</i>;
}
