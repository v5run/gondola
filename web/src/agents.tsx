import { createContext, useCallback, useContext, useEffect, useLayoutEffect, useMemo, useRef, useState, type ReactNode } from "react";
import { clock } from "./components/ui";

/** Agents grouped by workflow. Marks are two letters; the rail shows the groups in this order. */
export const AGENTS = [
  ["ledger", "Lg", "Ledger", "Records every order, task and decision", "Ledger"],
  ["controller", "Qu", "Queue and ladder", "Orders the queue, moves the admission ladder", "Present"],
  ["rush", "Ra", "Rush agent", "Steps in on triggers with one guarded action", "Present"],
  ["pricing", "Pr", "Pricing", "Promotes only where a station has room", "Present"],
  ["forecaster", "Fc", "Forecaster", "Nowcast every 15 minutes, drivers, tomorrow's prep", "Future"],
  ["exceptions", "Ex", "Exceptions agent", "Alerts, hands to Present, or notes for the close", "Review"],
  ["review", "Rv", "Review agent", "Well, wrong, causes and action items at close", "Review"],
  ["books", "Bk", "Books", "Cash, payouts and disputes", "Review"],
  ["report", "Rp", "Report", "Writes the report", "Review"],
  ["sentinel", "Sn", "Sentinel", "Decides who to text", "Review"],
] as const;
export type AgentKey = (typeof AGENTS)[number][0];
/** V2 agent names still used by the close stream and older screens, mapped to their new owner. */
const ALIAS: Record<string, AgentKey> = {
  coordinator: "review", stock: "ledger", demand: "forecaster", plan: "forecaster", analyst: "review", guard: "controller",
  "rush-agent": "rush", "outlook-agent": "forecaster", outlook: "forecaster", "review-agent": "review", "exceptions-agent": "exceptions", manager: "controller",
};
export const agentOf = (a: string): AgentKey | null => (AGENTS.some(([k]) => k === a) ? (a as AgentKey) : ALIAS[a] || null);
const MARK = Object.fromEntries(AGENTS.map(([k, m]) => [k, m])) as Record<AgentKey, string>;
const NAME = Object.fromEntries(AGENTS.map(([k, , n]) => [k, n])) as Record<AgentKey, string>;

interface Act { text: string; t?: string }
interface Ctx {
  pulse: (a: string, text: string, t?: string) => void;
  setRunning: (a: string, on: boolean) => void;
  last: Record<string, Act>; running: Set<string>; flash: Record<string, number>;
}
const AgentCtx = createContext<Ctx>({ pulse: () => {}, setRunning: () => {}, last: {}, running: new Set(), flash: {} });
export const useAgents = () => useContext(AgentCtx);

const setHl = (a: string | null) => { if (a) document.body.dataset.hl = a; else delete document.body.dataset.hl; };

/** Highlight rules for every agent: hovering a glyph rings the cards it owns, and vice versa. */
function useHighlightCss() {
  useEffect(() => {
    const el = document.createElement("style");
    el.textContent = AGENTS.map(([k]) => `body[data-hl="${k}"] [data-owner="${k}"]{box-shadow:0 0 0 3px var(--mint)}body[data-hl="${k}"] .rail [data-agent="${k}"]{background:var(--mint);color:var(--ink)}`).join("");
    document.head.appendChild(el);
    return () => el.remove();
  }, []);
}

export function AgentProvider({ children }: { children: ReactNode }) {
  const [last, setLast] = useState<Record<string, Act>>({});
  const [running, setRun] = useState<Set<string>>(new Set());
  const [flash, setFlash] = useState<Record<string, number>>({});
  useHighlightCss();
  const pulse = useCallback((raw: string, text: string, t?: string) => {
    const a = agentOf(raw);
    if (!a) return;
    setLast((l) => ({ ...l, [a]: { text, t } }));
    setFlash((f) => ({ ...f, [a]: (f[a] || 0) + 1 }));
  }, []);
  const setRunning = useCallback((raw: string, on: boolean) => {
    const a = agentOf(raw);
    if (!a) return;
    setRun((s) => { if (s.has(a) === on) return s; const n = new Set(s); if (on) n.add(a); else n.delete(a); return n; });
  }, []);
  const v = useMemo(() => ({ pulse, setRunning, last, running, flash }), [pulse, setRunning, last, running, flash]);
  return <AgentCtx.Provider value={v}>{children}</AgentCtx.Provider>;
}

/** The sidebar foot: agent marks grouped by workflow (Ledger, Present, Future, Review). Each lights when its agent acts. */
export function AgentRail() {
  const { last, running, flash } = useAgents();
  const groups = ["Ledger", "Present", "Future", "Review"];
  return (
    <div className="rail" aria-label="Agents">
      {groups.map((g) => (
        <div key={g} className="railg" role="list" aria-label={g}>
          {AGENTS.filter((x) => x[4] === g).map(([k, m, name, job]) =>
            <Glyph key={k} k={k} m={m} name={name} group={g} job={job} act={last[k]} on={running.has(k)} n={flash[k] || 0} />)}
        </div>
      ))}
    </div>
  );
}

function Glyph({ k, m, name, group, job, act, on, n }: { k: string; m: string; name: string; group: string; job: string; act?: Act; on: boolean; n: number }) {
  const [blink, setBlink] = useState(false);
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    setBlink(true); const t = setTimeout(() => setBlink(false), 900); return () => clearTimeout(t);
  }, [n]);
  const label = group === name ? name : `${group} · ${name}`;
  return (
    <div role="listitem" className={`ag${on ? " run" : ""}${blink ? " blink" : ""}`} data-agent={k} data-last={act?.text || ""} data-n={n} tabIndex={0}
      onMouseEnter={() => setHl(k)} onMouseLeave={() => setHl(null)} onFocus={() => setHl(k)} onBlur={() => setHl(null)} aria-label={`${label}${act ? `: ${act.text}` : ""}`}>
      {m}
      <span className="tip"><b>{label}</b>{act ? `${act.text}${act.t ? ` · ${clock(act.t)}` : ""}` : job}</span>
    </div>
  );
}

/** Tiny owner mark: drop inside any card; the card becomes that agent's (one owner per number). */
export function Own({ a, dark }: { a: AgentKey | string; dark?: boolean }) {
  const k = agentOf(a) || "ledger";
  const ref = useRef<HTMLElement>(null);
  useLayoutEffect(() => {
    const p = ref.current?.parentElement;
    if (p) p.dataset.owner = k;
    return () => { if (p && p.dataset.owner === k) delete p.dataset.owner; };
  }, [k]);
  return <i ref={ref} className={`og${dark ? " dark" : ""}`} title={NAME[k]} aria-hidden="true" onMouseEnter={() => setHl(k)} onMouseLeave={() => setHl(null)}>{MARK[k]}</i>;
}
