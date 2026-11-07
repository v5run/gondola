import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { useNavigate } from "react-router-dom";
import { api } from "./api/client";
import type { DayDetail, Driver, Explain, Finding, IntradayBin, ItemChange, ItemRow, Overview, RangeMetrics } from "./api/types";
import { CHANNELS, CH_COLOR, Icon, Skeleton, appName, clock, money, pct, useLoad } from "./components/ui";
import { addDays, daysBetween, fmtDay, fmtMonthDay, fmtRange, fromMin, toMin } from "./lib/dates";
import { minOf, shortEvent } from "./lib/events";
import { useApp, useLive } from "./state";
import { Own } from "./agents";

export type WhyTarget =
  | { kind: "day"; date: string }
  | { kind: "range"; start: string; end: string }
  | { kind: "bin"; date: string; time: string };

const keyOf = (t: WhyTarget | null) => (!t ? "" : t.kind === "day" ? `d${t.date}` : t.kind === "range" ? `r${t.start}${t.end}` : `b${t.date}${t.time}`);

interface Ctx {
  target: WhyTarget | null; anchor: string | null; drawer: boolean; pinned: boolean; collapsed: boolean;
  open: (t: WhyTarget, anchor: string) => void; close: () => void; popOut: () => void; setPinned: (p: boolean) => void;
  setCollapsed: (c: boolean) => void; prefetch: (t: WhyTarget) => void;
}
const WhyCtx = createContext<Ctx>(null as unknown as Ctx);
export const useWhy = () => useContext(WhyCtx);

function prefetch(t: WhyTarget) {
  const q = (p: Promise<unknown>) => p.catch(() => {});
  if (t.kind === "day") q(api.day(t.date));
  else if (t.kind === "bin") { q(api.day(t.date)); q(api.intraday(t.date)); }
  else { q(api.range(t.start, t.end)); q(api.items(t.start, t.end)); }
}

export function WhyProvider({ children }: { children: ReactNode }) {
  const [target, setTarget] = useState<WhyTarget | null>(null);
  const [anchor, setAnchor] = useState<string | null>(null);
  const [drawer, setDrawer] = useState(false);
  const [pinned, setPinned] = useState(false);
  const [collapsed, setCollapsed] = useState(false);
  const open = useCallback((t: WhyTarget, a: string) => {
    setTarget(t); setCollapsed(false);
    setDrawer((d) => { if (!d) setAnchor(a); return d; });
  }, []);
  const close = useCallback(() => { setTarget(null); setDrawer(false); setAnchor(null); }, []);
  const popOut = useCallback(() => { setDrawer(true); setAnchor(null); }, []);
  useEffect(() => {
    if (!target) return;
    const k = (e: KeyboardEvent) => { if (e.key === "Escape" && !document.querySelector(".pop, .drawer-scrim, .scrim")) close(); };
    addEventListener("keydown", k);
    return () => removeEventListener("keydown", k);
  }, [target, close]);
  const v: Ctx = { target, anchor, drawer, pinned, collapsed, open, close, popOut, setPinned, setCollapsed, prefetch };
  return <WhyCtx.Provider value={v}>{children}{drawer && target && <WhyWindow />}</WhyCtx.Provider>;
}

/** The inline breakdown, anchored under the chart that opened it. */
export function WhySlot({ anchor }: { anchor: string }) {
  const w = useWhy();
  const mine = !w.drawer && w.anchor === anchor && !!w.target;
  const [shown, setShown] = useState<{ t: WhyTarget } | null>(null);
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (mine && w.target) {
      setShown({ t: w.target });
      const r = requestAnimationFrame(() => setExpanded(true));
      return () => cancelAnimationFrame(r);
    }
    setExpanded(false);
    const t = setTimeout(() => setShown(null), 220);
    return () => clearTimeout(t);
  }, [mine, keyOf(w.target)]); // eslint-disable-line
  if (!shown) return null;
  const open = expanded && !w.collapsed;
  return (
    <section className={`why-slot${expanded ? " in" : ""}`} aria-label="Breakdown" data-testid="why"><Own a="analyst" />
      <WhyHead t={shown.t} inline />
      <div className={`why-body${open ? " open" : ""}`}><div><WhyBody t={shown.t} /></div></div>
    </section>
  );
}

function WhyHead({ t, inline }: { t: WhyTarget; inline?: boolean }) {
  const w = useWhy();
  const title = t.kind === "day" ? fmtDay(t.date) : t.kind === "range" ? fmtRange(t.start, t.end) : `${fmtMonthDay(t.date)} · ${clock(t.time)}–${clock(fromMin(toMin(t.time) + 15))}`;
  return (
    <div className="why-head">
      {inline && <button className={`iconbtn chev${w.collapsed ? "" : " open"}`} onClick={() => w.setCollapsed(!w.collapsed)} aria-expanded={!w.collapsed} aria-label={w.collapsed ? "Expand" : "Collapse"}>
        <Icon name="right" size={18} /></button>}
      <h3 data-testid="why-title">{title}</h3>
      <div className="why-act">
        {inline ? <button className="btn small light" onClick={w.popOut}>Open</button>
          : <button className={`btn small ${w.pinned ? "" : "light"}`} aria-pressed={w.pinned} onClick={() => w.setPinned(!w.pinned)}>{w.pinned ? "Pinned" : "Pin"}</button>}
        <button className="iconbtn" onClick={w.close} aria-label="Close breakdown"><Icon name="x" size={18} /></button>
      </div>
    </div>
  );
}

/** Side window: resizable from its left edge; stays open while pinned and swaps content on each click. */
function WhyWindow() {
  const w = useWhy();
  const [width, setWidth] = useState(() => Number(sessionStorage.getItem("why-w")) || 520);
  const ref = useRef<HTMLElement>(null);
  const drag = useRef(false);
  // the window docks beside the page instead of covering it, so charts stay clickable
  useEffect(() => {
    document.body.style.setProperty("--whyw", `${width}px`);
    document.body.classList.add("has-whywin");
    return () => { document.body.classList.remove("has-whywin"); };
  }, [width]);
  useEffect(() => {
    if (w.pinned) return;
    const down = (e: MouseEvent) => {
      const el = e.target as HTMLElement;
      if (ref.current?.contains(el) || el.closest("[data-why], .pop, .drawer-scrim, .toasts")) return;
      w.close();
    };
    const t = setTimeout(() => addEventListener("mousedown", down), 0);
    return () => { clearTimeout(t); removeEventListener("mousedown", down); };
  }, [w.pinned, w.close]); // eslint-disable-line
  return createPortal(
    <aside ref={ref} className="whywin" style={{ width }} role="dialog" aria-label="Breakdown window" data-testid="why-window">
      <div className="whywin-grip" aria-hidden="true"
        onPointerDown={(e) => { drag.current = true; (e.target as HTMLElement).setPointerCapture(e.pointerId); }}
        onPointerMove={(e) => { if (drag.current) setWidth(Math.max(380, Math.min(innerWidth - 160, innerWidth - e.clientX))); }}
        onPointerUp={() => { drag.current = false; sessionStorage.setItem("why-w", String(width)); }} />
      <WhyHead t={w.target!} />
      <div key={keyOf(w.target)} className="whywin-body enter"><WhyBody t={w.target!} /></div>
    </aside>, document.body);
}

/* ================= contents ================= */

function WhyBody({ t }: { t: WhyTarget }) {
  if (t.kind === "day") return <DayWhy date={t.date} />;
  if (t.kind === "range") return <RangeWhy start={t.start} end={t.end} />;
  return <BinWhy date={t.date} time={t.time} />;
}

const DAYPARTS: [string, number, number][] = [["Lunch", 660, 840], ["Afternoon", 840, 1020], ["Dinner", 1020, 1200], ["Late", 1200, 1440]];
/** When /day has no `explain`, build the same shape from the overview. */
export function deriveExplain(o: Overview): Explain {
  const vs = (k: string) => (o.vs_usual ? (o.vs_usual[`${k}_pct`] ?? o.vs_usual[k] ?? null) : null);
  const ticket = o.kpis?.avg_ticket || 0;
  const part = (pts: { time: string; orders: number }[], a: number, b: number) => pts.filter((p) => toMin(p.time) >= a && toMin(p.time) < b).reduce((s, p) => s + p.orders, 0);
  const usualTicket = ticket / (1 + (vs("avg_ticket") ?? 0));
  return {
    vs_usual: { net_sales_pct: vs("net_sales"), orders_pct: vs("orders") },
    vs_similar: null,
    drivers: {
      channel: o.channels.map((c) => ({ key: c.key, today: c.today, usual: c.usual, change: c.change ?? c.today - c.usual })),
      daypart: DAYPARTS.map(([k, a, b]) => { const td = part(o.curve_today, a, b) * ticket, us = part(o.curve_usual, a, b) * usualTicket; return { key: k, today: td, usual: us, change: td - us }; }),
    },
    context: { rain: o.context?.rain, events: o.context?.events || [] },
  };
}

const sgnMoney = (v: number) => `${v >= 0 ? "+" : "−"}${money(Math.abs(v))}`;
const label = (k: string) => appName[k] || k.charAt(0).toUpperCase() + k.slice(1).replace(/_/g, " ");

function Delta({ v, label: l }: { v: number | null | undefined; label: string }) {
  if (v === null || v === undefined) return null;
  return <span className={`num ${v < 0 ? "crit" : "good"}`}>{pct(v, 1)} <span className="ink2">{l}</span></span>;
}

function Stat({ name, value, deltas }: { name: string; value: string; deltas: [number | null | undefined, string][] }) {
  return (
    <div className="why-stat">
      <div className="ink2">{name}</div>
      <b className="num">{value}</b>
      <div className="why-deltas">{deltas.map(([v, l]) => <Delta key={l} v={v} label={l} />)}</div>
    </div>
  );
}

/** Ranked contributions as bars around zero: gains to the right, losses to the left. */
function Drivers({ title, rows, color }: { title: string; rows: Driver[]; color?: (k: string) => string | undefined }) {
  const r = [...rows].sort((a, b) => Math.abs(b.change) - Math.abs(a.change));
  const max = Math.max(1, ...r.map((x) => Math.abs(x.change)));
  return (
    <div className="why-block">
      <h4>{title}</h4>
      {r.map((x) => (
        <div key={x.key} className="drv-row" title={`${label(x.key)}: ${money(x.today)} vs ${money(x.usual)}`}>
          <span className="drv-k">{color?.(x.key) && <i className="sw" style={{ background: color(x.key) }} />}{label(x.key)}</span>
          <span className="drv-bar">
            <i className={x.change < 0 ? "neg" : "pos"} style={{ width: `${(Math.abs(x.change) / max) * 50}%` }} />
          </span>
          <b className={`num ${x.change < 0 ? "crit" : ""}`}>{sgnMoney(x.change)}</b>
        </div>
      ))}
    </div>
  );
}

function ItemsMoved({ up, down }: { up?: ItemChange[]; down?: ItemChange[] }) {
  if (!up?.length && !down?.length) return null;
  const row = (x: ItemChange) => <div key={x.item} className="drv-row simple"><span className="drv-k">{x.item}</span><b className={`num ${x.change < 0 ? "crit" : "good"}`}>{sgnMoney(x.change)}</b></div>;
  return (
    <div className="why-block">
      <h4>Items</h4>
      {(up || []).slice(0, 4).map(row)}
      {(down || []).slice(0, 4).map(row)}
    </div>
  );
}

function Context({ lines }: { lines: { text: string; tone?: "crit" }[] }) {
  if (!lines.length) return null;
  return (
    <div className="why-block">
      <h4>Context</h4>
      {lines.map((l) => <div key={l.text} className={`ctx-line${l.tone ? ` ${l.tone}` : ""}`}><i className="dot" />{l.text}</div>)}
    </div>
  );
}

function Findings({ list }: { list: Finding[] }) {
  const rank = (f: Finding) => (f.urgency === "urgent" ? 0 : f.urgency === "important" ? 1 : 2);
  const top = [...list].filter((f) => f.urgency === "urgent" || f.urgency === "important").sort((a, b) => rank(a) - rank(b)).slice(0, 5);
  if (!top.length) return null;
  return (
    <div className="why-block">
      <h4>Findings</h4>
      {top.map((f, i) => <div key={i} className="ctx-line"><i className="dot" style={{ background: f.urgency === "urgent" ? "var(--crit)" : "var(--ser)" }} />{f.title || f.kind}</div>)}
    </div>
  );
}

function contextLines(e: Explain, d?: DayDetail | null) {
  const c = e.context || {};
  const out: { text: string; tone?: "crit" }[] = [];
  if (c.rain) out.push({ text: "Rain" });
  if (c.snow) out.push({ text: "Snow" });
  if (typeof c.temp_high_c === "number") out.push({ text: `High ${Math.round(c.temp_high_c)}°C` });
  for (const ev of c.events || []) if (!/sold out/i.test(ev)) out.push({ text: ev.charAt(0).toUpperCase() + ev.slice(1) });
  const so = d?.close?.sold_out;
  if (so) out.push({ text: `Chashu sold out ${clock(so.at)} · ${so.app_cancels} app cancels`, tone: "crit" });
  else for (const ev of c.events || []) if (/sold out/i.test(ev)) out.push({ text: ev.charAt(0).toUpperCase() + ev.slice(1), tone: "crit" });
  return out;
}

function WhyLoading() {
  return <div className="why-grid"><Skeleton h={90} /><Skeleton h={150} /><Skeleton h={150} /><Skeleton h={110} /></div>;
}

function DayActions({ date, report }: { date: string; report?: boolean }) {
  const { setDate } = useApp();
  const nav = useNavigate();
  return (
    <div className="why-links">
      <button className="link" onClick={() => { setDate(date); nav("/"); }}>Open day</button>
      {report && <button className="link" onClick={() => { setDate(date); nav("/reports"); }}>Report</button>}
    </div>
  );
}

function DayWhy({ date }: { date: string }) {
  const d = useLoad(() => api.day(date), [date]);
  if (d.error) return <div className="crit">{d.error}</div>;
  if (!d.data) return <WhyLoading />;
  const o = d.data.overview;
  if (!o?.kpis) return <div className="why-grid"><Context lines={[{ text: "Closed" }, ...(o?.context?.events || []).map((t) => ({ text: t }))]} /></div>;
  const e = d.data.explain || deriveExplain(o);
  const sim = e.vs_similar;
  return (
    <div className="why-grid" data-testid="why-day">
      <div className="why-block stats">
        <Stat name="Net sales" value={money(o.kpis.net_sales)} deltas={[[e.vs_usual?.net_sales_pct, "vs usual"], [sim?.net_sales_pct, "vs similar"]]} />
        <Stat name="Orders" value={o.kpis.orders.toLocaleString()} deltas={[[e.vs_usual?.orders_pct, "vs usual"], [sim?.orders_pct, "vs similar"]]} />
      </div>
      {e.drivers?.channel?.length ? <Drivers title="Channel" rows={e.drivers.channel} color={(k) => CH_COLOR[k]} /> : null}
      {e.drivers?.daypart?.length ? <Drivers title="Daypart" rows={e.drivers.daypart} /> : null}
      <Context lines={contextLines(e, d.data)} />
      <ItemsMoved up={e.items_up} down={e.items_down} />
      <Findings list={d.data.close?.findings || []} />
      <DayActions date={date} report={!!d.data.report} />
    </div>
  );
}

function RangeWhy({ start, end }: { start: string; end: string }) {
  const w = useWhy();
  const n = daysBetween(start, end) + 1;
  const ps = addDays(start, -n), pe = addDays(start, -1);
  const r = useLoad(() => Promise.all([api.range(start, end), api.range(ps, pe).catch(() => null), api.items(start, end), api.items(ps, pe).catch(() => [] as ItemRow[])]), [start, end]);
  if (r.error) return <div className="crit">{r.error}</div>;
  if (!r.data) return <WhyLoading />;
  const [cur, prev, items, pitems] = r.data as [RangeMetrics, RangeMetrics | null, ItemRow[], ItemRow[]];
  const chan: Driver[] = prev ? CHANNELS.map((c) => ({ key: c, today: cur.by_channel[c] || 0, usual: prev.by_channel[c] || 0, change: (cur.by_channel[c] || 0) - (prev.by_channel[c] || 0) })) : [];
  const pmap = new Map(pitems.map((x) => [x.item, x.net_sales]));
  const moved = items.map((x) => ({ item: x.item, today: x.net_sales, usual: pmap.get(x.item) || 0, change: x.net_sales - (pmap.get(x.item) || 0) })).sort((a, b) => b.change - a.change);
  const day = (k: "best_day" | "worst_day") => {
    const v = cur[k]; if (!v) return null;
    const b = typeof v === "string" ? { date: v, net_sales: NaN } : v;
    const why = [b.rain ? "rain" : "", ...(b.events || [])].filter(Boolean).join(", ");
    return (
      <button className="clickrow" key={k} onClick={() => w.open({ kind: "day", date: b.date }, w.anchor || "range")} onMouseEnter={() => prefetch({ kind: "day", date: b.date })}>
        <span><span className="ink2" style={{ fontSize: 13 }}>{k === "best_day" ? "Best" : "Worst"}</span> <b>{fmtDay(b.date)}</b>{why && <span className="ink2"> · {why}</span>}</span>
        <b className="num">{money(b.net_sales)}</b>
      </button>
    );
  };
  return (
    <div className="why-grid" data-testid="why-range">
      <div className="why-block stats">
        <Stat name="Net sales" value={money(cur.net_sales)} deltas={[[cur.vs_prev_pct?.net_sales, "vs previous"]]} />
        <Stat name="Orders" value={cur.orders.toLocaleString()} deltas={[[cur.vs_prev_pct?.orders, "vs previous"]]} />
      </div>
      {chan.length > 0 && <Drivers title="Channel" rows={chan} color={(k) => CH_COLOR[k]} />}
      <ItemsMoved up={moved.filter((x) => x.change > 0).slice(0, 4)} down={moved.filter((x) => x.change < 0).reverse().slice(0, 4)} />
      <div className="why-block"><h4>Days</h4>{day("best_day")}{day("worst_day")}</div>
    </div>
  );
}

function BinWhy({ date, time }: { date: string; time: string }) {
  const live = useLive();
  const r = useLoad(() => Promise.all([api.intraday(date), api.day(date).catch(() => null)]), [date]);
  if (r.error) return <div className="crit">{r.error}</div>;
  if (!r.data) return <WhyLoading />;
  const [intra, d] = r.data;
  const b: IntradayBin | undefined = intra.bins.find((x) => x.time === time);
  const usualOrders = intra.usual.find((x) => x.time === time)?.orders ?? null;
  const ch = d?.overview?.channels || [];
  const usualTot = ch.reduce((a, c) => a + c.usual, 0);
  // the intraday "usual" has no channel split; share it by the usual day's channel mix
  const rows: Driver[] = b ? CHANNELS.map((c) => {
    const u = usualOrders !== null && usualTot ? usualOrders * ((ch.find((x) => x.key === c)?.usual || 0) / usualTot) : 0;
    return { key: c, today: b.by_channel[c] || 0, usual: u, change: (b.by_channel[c] || 0) - u };
  }) : [];
  const m0 = toMin(time), m1 = m0 + 15;
  const lines: { text: string; tone?: "crit" }[] = [];
  const so = d?.close?.sold_out;
  const soMin = so ? minOf(so.at) : null;
  if (so && soMin !== null && soMin < m1) lines.push({ text: soMin >= m0 ? `Chashu sold out ${clock(so.at)}` : `Chashu sold out since ${clock(so.at)}`, tone: "crit" });
  const bc = (b as IntradayBin & { cancels?: number })?.cancels;
  if (bc) lines.push({ text: `${bc} cancelled`, tone: "crit" });
  if (live.date === date) for (const e of live.events) if (toMin(e.t) >= m0 && toMin(e.t) < m1) lines.push({ text: shortEvent(e), tone: e.kind === "pause" || e.kind === "sold_out" ? "crit" : undefined });
  const vsU = b && usualOrders ? b.orders / usualOrders - 1 : null;
  return (
    <div className="why-grid" data-testid="why-bin">
      <div className="why-block stats">
        <Stat name="Orders" value={b ? String(Math.round(b.orders)) : "–"} deltas={[[vsU, "vs usual"]]} />
        <Stat name="Net sales" value={b ? money(b.net_sales) : "–"} deltas={[]} />
      </div>
      {rows.length > 0 && <div className="why-block"><h4>Channel</h4>
        {rows.map((x) => (
          <div key={x.key} className="drv-row simple">
            <span className="drv-k"><i className="sw" style={{ background: CH_COLOR[x.key] }} />{appName[x.key]}</span>
            <b className="num">{Math.round(x.today)}</b>
            <span className={`num ${x.change < 0 ? "crit" : "good"}`} style={{ minWidth: 48, textAlign: "right" }}>{x.usual ? `${x.change >= 0 ? "+" : "−"}${Math.abs(x.change).toFixed(1)}` : ""}</span>
          </div>
        ))}
      </div>}
      <Context lines={lines} />
      <DayActions date={date} report={!!d?.report} />
    </div>
  );
}

