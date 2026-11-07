import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import { tri, type LedgerEvent, type PastSummary } from "../api/tri";
import type { IntradayBin, LiveOrder, Point } from "../api/types";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { ChannelLegend, DayCurve, HBar, StackedBins } from "../components/charts";
import { CH_COLOR, ErrorBox, Segmented, Skeleton, Tween, appName, clock, money, pct, useLoad } from "../components/ui";
import { dowName, fmtMonthDay, fromMin, toMin } from "../lib/dates";
import { actionText } from "../live";
import { useApp, useClock, useLive } from "../state";
import { WhySlot, useWhy } from "../why";
import { Own, useAgents } from "../agents";

const bin = (t: string) => fromMin(Math.floor(toMin(t) / 15) * 15);
function curveFromOrders(orders: LiveOrder[], nowMin: number): Point[] {
  const out = new Map<string, number>();
  for (let m = 11 * 60; m + 15 <= nowMin + 1; m += 15) out.set(fromMin(m), 0);
  for (const o of orders) { const b = bin(o.t); out.set(b, (out.get(b) || 0) + 1); }
  return [...out].map(([time, orders]) => ({ time, orders })).sort((a, b) => a.time.localeCompare(b.time));
}
function binsFromFeed(orders: LiveOrder[], base: IntradayBin[], nowMin: number): IntradayBin[] {
  const first = orders.length ? toMin(bin(orders[0].t)) : nowMin;
  const m = new Map<string, IntradayBin>();
  for (const b of base) if (toMin(b.time) < first) m.set(b.time, b);
  for (const o of orders) {
    const k = bin(o.t);
    const b = m.get(k) || { time: k, orders: 0, net_sales: 0, by_channel: { in_store: 0, doordash: 0, ubereats: 0, grubhub: 0 } };
    if (!/cancel/.test(o.status)) { b.orders += 1; b.net_sales += o.subtotal || 0; b.by_channel[o.channel] = (b.by_channel[o.channel] || 0) + 1; }
    m.set(k, b);
  }
  return [...m.values()].filter((b) => toMin(b.time) <= nowMin).sort((a, b) => a.time.localeCompare(b.time));
}

const FILTERS: [string, string][] = [["all", "All"], ["orders", "Orders"], ["kitchen", "Kitchen"], ["decisions", "Decisions"], ["exceptions", "Exceptions"]];
const TYPES: Record<string, string[]> = {
  orders: ["order.received", "order.accepted", "order.quoted", "order.deferred", "order.declined", "order.handed_off", "order.cancelled", "order.refunded", "courier.eta_updated", "courier.arrived", "customer.arrived"],
  kitchen: ["task.started", "task.finished"],
  decisions: ["action.applied", "forecast.issued", "review.completed", "kb.changed"],
  exceptions: ["exception.raised", "exception.resolved", "payout.report_arrived", "cash.counted"],
};

export default function Orders() {
  const { date, now, inService, view } = useApp();
  const live = useLive();
  const t = useClock();
  const why = useWhy();
  const { pulse } = useAgents();
  const isToday = !!now && date === now.today;
  const running = isToday && inService;
  const ov = useLoad(() => (date ? api.overview(date) : new Promise<never>(() => {})), [date]);
  const intra = useLoad(() => (date ? api.intraday(date) : new Promise<never>(() => {})), [date]);
  const [sum, setSum] = useState<PastSummary | null>(null);
  const [sumErr, setSumErr] = useState<string | null>(null);
  useEffect(() => {
    if (!date) return;
    let dead = false;
    setSum(null); setSumErr(null);
    const pull = () => tri.past.summary(date).then((s) => !dead && setSum(s)).catch((e) => !dead && setSumErr(String(e.message)));
    pull();
    const id = running ? setInterval(pull, 10000) : undefined;
    return () => { dead = true; if (id) clearInterval(id); };
  }, [date, running]);

  const o = ov.data && ov.data.date === date ? ov.data : null;
  const isLive = view === "live" && running && live.date === date && live.status !== "idle" && !!live.cur;
  const nowMin = isLive && t ? toMin(t.slice(0, 5)) : null;
  const liveCurve = useMemo(() => {
    if (!isLive || nowMin === null) return [];
    return curveFromOrders(live.orders, nowMin).filter((p) => toMin(p.time) + 15 <= nowMin);
  }, [isLive, live.orders.length, nowMin === null ? -1 : Math.floor(nowMin / 15)]); // eslint-disable-line
  const bins = useMemo(() => {
    const base = intra.data?.bins || [];
    return isLive && nowMin !== null ? binsFromFeed(live.orders, base, nowMin) : base;
  }, [isLive, intra.data, live.orders.length, nowMin]); // eslint-disable-line
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const dow = date ? dowName(date) : "";
  const sel = why.target?.kind === "bin" && why.target.date === date ? why.target.time : null;

  const s = sum && sum.date === date ? sum : null;
  const metPct = s && s.promises_total ? s.promises_met / s.promises_total : null;
  const sales = s ? Object.values(s.by_channel).reduce((a, c) => a + (c.sales || 0), 0) : null;
  const chans = s ? Object.entries(s.by_channel).filter(([, c]) => c.orders || c.sales).sort((a, b) => b[1].sales - a[1].sales) : [];
  const cmax = Math.max(1, ...chans.map(([, c]) => c.sales));
  const closedDay = !!o && (o.closed || !o.kpis) && !s?.processed;

  return (
    <Page title="Past">
      {sumErr && !s && <ErrorBox error={sumErr} />}
      {!o && !ov.error && <Skeleton h={300} />}
      {o && <section className="hero tonight-hero" aria-label="Orders processed"><Own a="ledger" dark /><Info k="processed" dark />
        <div>
          <div className="lab">Orders processed{s?.cutoff ? ` · ${clock(s.cutoff)}` : ""}</div>
          <div className="big" data-testid="processed">{s ? <Tween value={s.processed} /> : closedDay ? "Closed" : "–"}</div>
          <div className="drv">
            <div><span>Promises met</span><b>{metPct === null ? "–" : pct(metPct, 0, false)}</b></div>
            <div><span>Net sales</span><b>{sales === null ? "–" : <Tween value={sales} fmt={(v) => money(v)} />}</b></div>
            <div><span>Decisions</span><b>{s ? s.actions_count : "–"}</b></div>
            {o.context?.rain && <div><span>Rain</span><b>Yes</b></div>}
          </div>
        </div>
        <div>
          <div className="legend-inline"><span><i className="sw" style={{ background: "#b8e986" }} />{date ? fmtMonthDay(date) : ""}</span><span><i className="sw" style={{ background: "#8cc8ff" }} />Usual {dow}</span></div>
          <DayCurve today={isLive ? liveCurve : o.curve_today} usual={o.curve_usual} nowMin={nowMin} H={250} todayLabel={fmtMonthDay(date)} usualLabel={`Usual ${dow}`}
            onHover={(tm) => why.prefetch({ kind: "bin", date, time: tm })} onPick={(p) => why.open({ kind: "bin", date, time: p.time }, "past-top")} />
        </div>
      </section>}

      <div className="grid5" data-testid="past-kpis">
        <Kpi k="promises_met" label="Promises met" value={metPct === null ? null : metPct} fmt={(v) => pct(v, 0, false)} sub={s ? `${s.promises_met} of ${s.promises_total}` : undefined} />
        <Kpi k="avg_wait" label="Average wait" value={s?.avg_wait_min ?? null} fmt={(v) => `${v.toFixed(1)} min`} />
        <Kpi k="worst_wait" label="Worst wait" value={s?.worst_wait_min ?? null} fmt={(v) => `${v.toFixed(0)} min`} bad={(s?.worst_wait_min ?? 0) > 10} />
        <Kpi k="avg_hold" label="Food hold" value={s?.avg_hold_min ?? null} fmt={(v) => `${v.toFixed(1)} min`} />
        <Kpi k="ledger_cancels" label="Cancels" value={s?.cancels ?? null} bad={(s?.cancels ?? 0) > 0} sub={s ? `${s.refunds} refund${s.refunds === 1 ? "" : "s"}` : undefined} />
      </div>
      <WhySlot anchor="past-top" />

      <div className="past-grid">
        <LedgerFeed date={date} live={running} onNew={(e) => { if (e.type === "order.handed_off") pulse("ledger", `handed off ${e.payload.order_id}`, e.ts.slice(11, 16)); }} />
        <div className="card"><Own a="ledger" /><Info k="by_channel_ledger" />
          <div className="cardhead"><h3>By channel</h3></div>
          {!s && <Skeleton h={200} />}
          {chans.map(([c, v]) => (
            <div key={c} className="chanrow2">
              <span><i className="sw" style={{ background: CH_COLOR[c] || "#8b938e" }} />{appName[c] || c}</span>
              <HBar value={v.sales} max={cmax} color={CH_COLOR[c] || "#8b938e"} h={10} />
              <span className="num ink2">{v.orders}</span>
              <b className="num">{money(v.sales)}</b>
            </div>
          ))}
        </div>
      </div>

      <div className="card"><Own a="ledger" /><Info k="every_15" />
        <div className="cardhead"><h3>Every 15 minutes</h3><ChannelLegend hidden={hidden} toggle={(c) => setHidden((h) => { const n = new Set(h); if (n.has(c)) n.delete(c); else n.add(c); return n; })} /></div>
        {intra.error ? <ErrorBox error={intra.error} retry={intra.reload} /> : !intra.data ? <Skeleton h={240} /> :
          <StackedBins bins={bins} usual={intra.data.usual} hidden={hidden} nowMin={nowMin} selected={sel}
            onHover={(b) => why.prefetch({ kind: "bin", date, time: b.time })} onPick={(b) => why.open({ kind: "bin", date, time: b.time }, "past-bins")} />}
        <WhySlot anchor="past-bins" />
      </div>
    </Page>
  );
}

function Kpi({ k, label, value, fmt = (v) => Math.round(v).toLocaleString("en-US"), sub, bad }: { k: string; label: string; value: number | null; fmt?: (v: number) => string; sub?: string; bad?: boolean }) {
  return (
    <div className="card kpi" data-k={k}><Info k={k} />
      <div className="l">{label}</div>
      <div className={`v${bad ? " crit" : ""}`}>{value === null ? "–" : <Tween value={value} fmt={fmt} />}</div>
      {sub && <div className="d ink2" style={{ color: "var(--ink2)", fontWeight: 500 }}>{sub}</div>}
    </div>
  );
}

/* ================= the ledger feed ================= */

const KIND: [RegExp, string][] = [[/^order\.|^customer\./, "Order"], [/^task\./, "Kitchen"], [/^courier\./, "Courier"], [/^action\./, "Decision"],
  [/^forecast\./, "Forecast"], [/^exception\./, "Exception"], [/^payout|^cash/, "Books"], [/^review|^kb/, "Review"]];
const kindOf = (t: string) => KIND.find(([r]) => r.test(t))?.[1] || t;
const m1 = (v: unknown) => (typeof v === "number" ? v.toFixed(1) : String(v ?? ""));

export function describe(e: LedgerEvent): { text: string; tone?: "crit" | "good"; ch?: string } {
  const p = e.payload || {};
  const id = p.order_id || "";
  const ch = p.channel;
  switch (e.type) {
    case "order.received": return { text: `${id} from ${appName[ch] || ch || "?"}${p.items?.length ? ` · ${p.items.join(", ")}` : ""}${typeof p.subtotal === "number" ? ` · ${money(p.subtotal, 2)}` : ""}`, ch };
    case "order.accepted": return { text: `${id} accepted${p.ladder_level && p.ladder_level !== "normal" ? ` (${String(p.ladder_level).replace(/_/g, " ")})` : ""}`, ch };
    case "order.quoted": return { text: `${id} quoted${p.quoted_ready ? ` ready ${clock(p.quoted_ready)}` : " longer"}`, ch };
    case "order.deferred": return { text: `${id} deferred: ${p.reason || ""}`, ch };
    case "order.declined": return { text: `${id} declined: ${p.reason || ""}`, tone: "crit", ch };
    case "order.handed_off": return { text: `${id} handed off${typeof p.wait_min === "number" && p.wait_min > 0 ? ` · waited ${m1(p.wait_min)} min` : ""}${p.hold_min ? ` · held ${m1(p.hold_min)} min` : ""}${p.late_min > 0 ? ` · ${m1(p.late_min)} min late` : ""}`, tone: p.late_min > 0 ? "crit" : undefined, ch };
    case "order.cancelled": return { text: `${id} cancelled${p.reason ? `: ${p.reason}` : ""}${typeof p.amount === "number" ? ` · ${money(p.amount, 2)}` : ""}`, tone: "crit", ch };
    case "order.refunded": return { text: `${id} refunded${typeof p.amount === "number" ? ` ${money(p.amount, 2)}` : ""}${p.reason ? `: ${p.reason}` : ""}`, tone: "crit", ch };
    case "task.started": return { text: `${cap(p.station)}: ${p.item} for ${id}` };
    case "task.finished": return { text: `${cap(p.station)}: ${p.item} done${p.actual_min !== undefined ? ` in ${m1(p.actual_min)} min` : ""}${p.planned_min !== undefined ? ` (planned ${m1(p.planned_min)})` : ""}` };
    case "courier.eta_updated": return { text: `${id} courier ${p.eta ? clock(p.eta) : ""}${p.distance_km !== undefined && p.distance_km !== null ? ` · ${m1(p.distance_km)} km` : ""}`, ch };
    case "courier.arrived": return { text: `${id} courier arrived`, ch };
    case "customer.arrived": return { text: `${id} customer arrived`, ch };
    case "action.applied": return { text: `${actionText(p as never)}${p.reason ? ` · ${p.reason}` : ""}` };
    case "forecast.issued": return { text: `Forecast ${p.horizon === "rest_of_day" ? "rest of day" : p.for_date || ""}: ${p.total ? `${Math.round(p.total.p50)} (${Math.round(p.total.p10)}–${Math.round(p.total.p90)})` : ""}` };
    case "exception.raised": return { text: p.title || p.kind || "Exception", tone: /high|crit/.test(p.severity || "") ? "crit" : undefined };
    case "exception.resolved": return { text: `Resolved: ${p.title || p.id || ""}`, tone: "good" };
    case "payout.report_arrived": return { text: `${appName[ch] || ch || "App"} payout report arrived` };
    case "cash.counted": return { text: `Cash counted${typeof p.counted === "number" ? ` ${money(p.counted, 2)}` : ""}` };
    case "review.completed": return { text: "Day review written", tone: "good" };
    case "kb.changed": return { text: `Knowledge: ${p.op || "changed"} ${p.statement || p.id || ""}` };
    default: return { text: e.type };
  }
}
/** The ledger may hold the same order event from two writers (order-level "pos" rows and Present's timed rows):
 *  keep one per (type, order), preferring the timed writer, and drop hand-offs without times. */
export function dedupe(evs: LedgerEvent[]): LedgerEvent[] {
  const best = new Map<string, LedgerEvent>();
  const rank = (e: LedgerEvent) => (e.source === "pos" ? 0 : 1);
  for (const e of evs) {
    const id = e.payload?.order_id;
    if (!id || !/^(order|courier|customer)\./.test(e.type)) continue;
    const k = `${e.type}|${id}`;
    const b = best.get(k);
    if (!b || rank(e) > rank(b)) best.set(k, e);
  }
  return evs.filter((e) => {
    const id = e.payload?.order_id;
    if (e.type === "order.handed_off" && e.payload?.handed === null && e.source === "pos" && best.get(`${e.type}|${id}`) === e) return false;
    return !id || !/^(order|courier|customer)\./.test(e.type) || best.get(`${e.type}|${id}`) === e;
  });
}

const cap = (s: unknown) => { const x = String(s || ""); return x.charAt(0).toUpperCase() + x.slice(1); };

function LedgerFeed({ date, live, onNew }: { date: string; live: boolean; onNew: (e: LedgerEvent) => void }) {
  const [f, setF] = useState("all");
  const [events, setEvents] = useState<LedgerEvent[] | null>(null);
  const [next, setNext] = useState<number | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [more, setMore] = useState(false);
  const seen = useRef<Set<number> | null>(null);
  const lastDate = useRef("");
  const newIds = useRef(new Set<number>());
  const onNewRef = useRef(onNew); onNewRef.current = onNew;
  useEffect(() => {
    if (!date) return;
    let dead = false;
    if (lastDate.current !== date) setEvents(null); // a new filter keeps the old lines until the new ones arrive
    lastDate.current = date; setErr(null); seen.current = null;
    const types = f === "all" ? undefined : TYPES[f];
    let fresh = true;
    const pull = () => tri.past.ledger(date, { types, limit: 80 }).then((r) => {
      if (dead) return;
      if (seen.current) { newIds.current = new Set(r.events.filter((e) => !seen.current!.has(e.id)).map((e) => e.id)); r.events.filter((e) => newIds.current.has(e.id)).forEach((e) => onNewRef.current(e)); }
      seen.current = new Set(r.events.map((e) => e.id));
      setEvents((old) => {
        if (!old || fresh) { fresh = false; setNext(r.next_before_id); return r.events; }
        const ids = new Set(r.events.map((e) => e.id));
        const last = r.events[r.events.length - 1];
        const tail = last ? old.filter((e) => !ids.has(e.id) && (e.ts < last.ts || (e.ts === last.ts && e.id < last.id))) : [];
        return [...r.events, ...tail];
      });
    }).catch((e) => !dead && setErr(String(e.message)));
    pull();
    const id = live ? setInterval(pull, 5000) : undefined;
    return () => { dead = true; if (id) clearInterval(id); };
  }, [date, f, live]);
  const loadMore = async () => {
    if (!next) return;
    setMore(true);
    try {
      const r = await tri.past.ledger(date, { types: f === "all" ? undefined : TYPES[f], limit: 120, before_id: next });
      setEvents((old) => [...(old || []), ...r.events.filter((e) => !(old || []).some((x) => x.id === e.id))]); setNext(r.next_before_id);
    } catch (e) { setErr(String((e as Error).message)); }
    finally { setMore(false); }
  };
  return (
    <div className="card"><Own a="ledger" /><Info k="ledger_feed" />
      <div className="cardhead"><h3>Ledger</h3><Segmented label="Show" value={f} onChange={setF} options={FILTERS} /></div>
      {err && <ErrorBox error={err} />}
      {!events && !err && <Skeleton h={360} />}
      {events && <div className="ledger" data-testid="ledger" aria-live="off">
        {events.length === 0 && <div className="empty">Nothing recorded yet</div>}
        {dedupe(events).map((e) => {
          const d = describe(e);
          return (
            <div key={e.id} className={`lrow${newIds.current.has(e.id) ? " new" : ""}`} data-type={e.type}>
              <span className="num muted">{clock(e.ts.slice(11, 16))}</span>
              <i className="sw" style={{ background: d.ch ? CH_COLOR[d.ch] || "#8b938e" : d.tone === "crit" ? "var(--crit)" : "var(--ink2)", margin: 0 }} />
              <span className="lk">{kindOf(e.type)}</span>
              <span className={`lt${d.tone ? ` ${d.tone}` : ""}`}>{d.text}</span>
            </div>
          );
        })}
        {next && <button className="link lmore" onClick={loadMore} disabled={more}>{more ? "Loading" : "Earlier"}</button>}
      </div>}
    </div>
  );
}
