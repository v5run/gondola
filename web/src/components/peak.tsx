/** Shared pieces for the simple Present screens (Cook order, Apps): data, status bar and plain-language helpers. */
import { useEffect, useState } from "react";
import { levelKey, tri, type PresentState, type QueueRow } from "../api/tri";
import { appName } from "./ui";
import { useApp } from "../state";
import { usePlayback } from "../playback";
import { usePresentLive } from "../live";

/** Today's state from the live stream, a past day read once, or the playback frame. */
export function usePresentState() {
  const { date, now } = useApp();
  const live = usePresentLive();
  const playback = usePlayback();
  const isToday = !!now && date === now.today;
  const [other, setOther] = useState<PresentState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!date || isToday || playback.active) return;
    let on = true;
    setOther(null); setErr(null);
    tri.present.state(date).then((s) => on && setOther(s)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [date, isToday, n, playback.active]);
  const st = playback.active ? playback.frame?.present ?? null : isToday ? live.state : other && other.date === date ? other : null;
  const error = playback.active ? null : isToday ? (live.status === "error" && !st ? live.error || null : null) : err;
  const retry = () => (isToday ? live.refresh() : setN((x) => x + 1));
  return { st, error, retry, date, playback, live, closed: st?.phase === "closed" && !playback.active };
}

export const chName = (c: string) => appName[c] || c.replace(/_/g, " ").replace(/^./, (x) => x.toUpperCase());
export const num = (v: unknown): number => (typeof v === "number" ? v : v && typeof v === "object" ? Number((v as any).min ?? (v as any).value ?? 0) || 0 : 0);
export const isLate = (r: QueueRow) => (r.predicted_late_min ?? 0) > 0 || (r.slack_min !== null && r.slack_min < 0);
export const tone = (r: QueueRow) => (isLate(r) ? "late" : r.slack_min !== null && r.slack_min < 5 ? "tight" : "ok");
export const hm = (t?: string | null) => (t ? t.slice(0, 5) : "");
export const itemsText = (items: string[]) => {
  const counts = new Map<string, number>();
  for (const i of items) counts.set(i, (counts.get(i) || 0) + 1);
  return [...counts].map(([i, n]) => (n > 1 ? `${n}× ${i}` : i)).join(", ");
};
export const ordinal = (n: number) => `${n}${n % 100 >= 11 && n % 100 <= 13 ? "th" : ["th", "st", "nd", "rd"][n % 10] || "th"}`;

const STATUS: Record<string, { label: string; cls: string; hint: string }> = {
  promote: { label: "Running smoothly", cls: "ok", hint: "Kitchen has room. Cook in the order shown." },
  normal: { label: "Running smoothly", cls: "ok", hint: "Cook in the order shown." },
  quote: { label: "Busy", cls: "tight", hint: "Delivery apps are quoting longer times." },
  pause_items: { label: "Very busy", cls: "warn", hint: "Some slow dishes are paused on delivery apps." },
  busy: { label: "Overloaded", cls: "late", hint: "Some delivery apps are not taking orders." },
};

export function appNotices(st: PresentState): string[] {
  const out: string[] = [];
  for (const [ch, s] of Object.entries(st.channels || {})) {
    if (s.state === "busy") out.push(`${chName(ch)} paused (not taking orders)`);
    else if (s.state === "paused_items") out.push(`${chName(ch)}: ${(s.paused_items || []).join(", ") || "some items"} paused`);
    else if (s.state === "quoted" && s.quoted_extra_min) out.push(`${chName(ch)} quoting +${s.quoted_extra_min} min`);
  }
  return out;
}

/** One headline, four numbers, the time. Never says "smooth" while orders are late. */
export function StatusBar({ st, closed }: { st: PresentState; closed: boolean }) {
  const q = st.queue || [];
  const waiting = q.filter((r) => r.status === "queued").length;
  const cooking = q.filter((r) => r.status === "cooking" || r.status === "packing");
  const ready = q.filter((r) => r.status === "ready").length;
  const late = q.filter((r) => r.status !== "ready" && isLate(r)).length;
  const base = STATUS[levelKey(st.ladder?.level ?? st.ladder?.name)];
  const s = closed ? { label: "Closed", cls: "ok", hint: "Service has ended for this day." }
    : late && base.cls === "ok" ? { label: `${late} order${late > 1 ? "s" : ""} behind`, cls: "tight", hint: "Follow the cook order — late orders are already moved up where possible." } : base;
  const notices = appNotices(st);
  return (
    <section className={`pk-status ${s.cls}`} aria-live="polite">
      <div className="pk-state"><span className="pk-dot" /><div><b>{s.label}</b><span>{s.hint}</span></div></div>
      <div className="pk-counts num">
        <div><b>{waiting}</b><span>waiting</span></div>
        <div><b>{cooking.length}</b><span>cooking</span></div>
        <div><b>{ready}</b><span>ready</span></div>
        <div className={late ? "late" : ""}><b>{late}</b><span>running late</span></div>
      </div>
      <div className="pk-time num"><span>Now</span><b>{hm(st.now)}</b></div>
      {notices.length > 0 && <div className="pk-notices">{notices.map((t) => <span key={t}>{t}</span>)}</div>}
    </section>
  );
}
