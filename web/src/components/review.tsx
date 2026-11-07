import { useNavigate } from "react-router-dom";
import { useApp } from "../state";
import { fmtMonthDay } from "../lib/dates";

const ISO = /^\d{4}-\d{2}-\d{2}$/;
/** Flattens whatever evidence a backend sent (string, list, objects) into short strings. */
export function evidenceList(ev: unknown): string[] {
  if (ev === null || ev === undefined || ev === "") return [];
  if (Array.isArray(ev)) return ev.flatMap(evidenceList);
  if (typeof ev === "object") {
    const o = ev as Record<string, unknown>;
    if (typeof o.text === "string") return [o.text];
    // structured evidence: the dates it rests on (each opens that day), found anywhere inside
    const out = new Set<string>();
    const walk = (v: unknown) => {
      if (typeof v === "string") { if (ISO.test(v)) out.add(v); }
      else if (Array.isArray(v)) v.forEach(walk);
      else if (v && typeof v === "object") Object.values(v).forEach(walk);
    };
    walk(o);
    return [...out].sort().reverse();
  }
  return [String(ev)];
}

/** Evidence: dates open that day in Past; anything else is plain text. */
export function Evidence({ ev, max = 6 }: { ev: unknown; max?: number }) {
  const { setDate, store } = useApp();
  const nav = useNavigate();
  const list = evidenceList(ev).slice(0, max);
  if (!list.length) return null;
  return (
    <span className="evid">
      {list.map((e, i) => ISO.test(e) && (!store || e <= store.today)
        ? <button key={`${e}-${i}`} className="link" onClick={() => { setDate(e); nav("/past"); }} data-evidence-date={e}>{fmtMonthDay(e)}</button>
        : <span key={`${e}-${i}`}>{e}</span>)}
    </span>
  );
}

export const STATUS_DOT: Record<string, string> = {
  open: "var(--warn)", done: "var(--good)", not_working: "var(--crit)", active: "var(--good)", proposed: "var(--muted)",
  needs_approval: "var(--warn)", retired: "#c3cbc5", rejected: "var(--crit)",
};
export const STATUS_NAME: Record<string, string> = {
  open: "Open", done: "Done", not_working: "Not working", active: "Active", proposed: "Proposed", needs_approval: "Needs approval", retired: "Retired", rejected: "Rejected",
};
export function Status({ s }: { s: string }) {
  return <span className="stat" data-status={s}><i className="dot" style={{ background: STATUS_DOT[s] || "var(--muted)" }} />{STATUS_NAME[s] || s.replace(/_/g, " ")}</span>;
}

/** An action item's measure, as text: "unavailable cancels down from 2.5 (28 days)". */
export function measureText(m: unknown): string {
  if (!m) return "";
  if (typeof m === "string") return m;
  const o = m as Record<string, any>;
  const metric = String(o.metric || "").replace(/_/g, " ");
  const dir = o.direction === "down" ? "down" : o.direction === "up" ? "up" : "";
  const base = typeof o.baseline === "number" ? ` from ${Math.round(o.baseline * 10) / 10}` : "";
  return `${metric}${dir ? ` ${dir}` : ""}${base}${o.window_days ? ` over ${o.window_days} days` : ""}`.trim();
}
