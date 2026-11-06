import { useMemo, useState } from "react";
import { useNavigate } from "react-router-dom";
import { api } from "../api/client";
import { useEffect } from "react";
import type { IntradayBin, LiveOrder, Point } from "../api/types";
import { Page } from "../components/Page";
import { ChannelLegend, DayCurve, HBar, StackedBins } from "../components/charts";
import {
  CHANNELS, CH_COLOR, ErrorBox, FoodIcon, NumberField, Skeleton, SkeletonCard, Tween, appName, clock, money, pct, useLoad,
} from "../components/ui";
import { dowName, fmtMonthDay, fromMin, toMin } from "../lib/dates";
import { shortEvent } from "../lib/events";
import { useApp, useClock, useLive } from "../state";
import { WhySlot, useWhy, type WhyTarget } from "../why";
import { Own } from "../agents";

const bin = (t: string) => fromMin(Math.floor(toMin(t) / 15) * 15);

/** Orders placed per 15 minutes from the live order feed (every status, as the usual curve counts them). */
function curveFromOrders(orders: LiveOrder[], nowMin: number): Point[] {
  const out = new Map<string, number>();
  for (let m = 11 * 60; m + 15 <= nowMin + 1; m += 15) out.set(fromMin(m), 0); // quiet bins so far read as 0
  for (const o of orders) { const b = bin(o.t); out.set(b, (out.get(b) || 0) + 1); }
  return [...out].map(([time, orders]) => ({ time, orders })).sort((a, b) => a.time.localeCompare(b.time));
}

/** Channel bins from the order feed; bins before the feed began come from the day's intraday data. */
function binsFromFeed(orders: LiveOrder[], base: IntradayBin[], nowMin: number): IntradayBin[] {
  const first = orders.length ? toMin(bin(orders[0].t)) : nowMin;
  const m = new Map<string, IntradayBin>();
  for (const b of base) if (toMin(b.time) < first) m.set(b.time, b);
  for (const o of orders) {
    const k = bin(o.t);
    const b = m.get(k) || { time: k, orders: 0, net_sales: 0, by_channel: { in_store: 0, doordash: 0, ubereats: 0, grubhub: 0 } };
    if (o.status === "cancelled" || o.status === "canceled") { m.set(k, b); continue; }
    b.orders += 1; b.net_sales += o.subtotal || 0; b.by_channel[o.channel] = (b.by_channel[o.channel] || 0) + 1;
    m.set(k, b);
  }
  return [...m.values()].sort((a, b) => a.time.localeCompare(b.time));
}

export default function Tonight() {
  const { date, view, store, now, inService } = useApp();
  const live = useLive();
  const t = useClock();
  const why = useWhy();
  const nav = useNavigate();
  const ov = useLoad(() => (date ? api.overview(date) : new Promise<never>(() => {})), [date]);
  const intra = useLoad(() => (date ? api.intraday(date) : new Promise<never>(() => {})), [date]);
  const day = useLoad(() => (date ? api.day(date).catch(() => null) : new Promise<never>(() => {})), [date]);
  const items = useLoad(() => (date ? api.items(date, date).catch(() => null) : new Promise<never>(() => {})), [date]);
  const [hidden, setHidden] = useState<Set<string>>(new Set());
  const [open, setOpen] = useState(false);
  const o = ov.data && ov.data.date === date ? ov.data : null;
  const closed = !!o && (o.closed || !o.kpis);
  const isToday = !!now && date === now.today;
  // live = today in service on the real clock; a finished night (or any earlier day) reads as the whole day
  const isLive = view === "live" && isToday && inService && live.date === date && live.status !== "idle" && !closed && !!live.cur;
  const tick = isLive ? live.cur : null;
  const nowMin = isLive && t ? toMin(t.slice(0, 5)) : null;
  // opening time arrives while the page is open: the first real order brings the day in
  const firstIn = live.date === date && live.orders.length > 0;
  useEffect(() => { if (o?.not_open_yet && firstIn) ov.reload(); }, [firstIn]); // eslint-disable-line
  const dow = date ? dowName(date) : "";
  const vs = (k: string): number | null => (o?.vs_usual ? o.vs_usual[`${k}_pct`] ?? o.vs_usual[k] ?? null : null);

  // ---- live derivations
  // the bin still in progress would read as a dip, so the line stops at the last complete 15 minutes
  const liveCurve = useMemo(() => {
    if (!isLive || nowMin === null) return [];
    const c = curveFromOrders(live.orders, nowMin);
    return live.status === "done" ? c : c.filter((p) => toMin(p.time) + 15 <= nowMin);
  }, [isLive, live.orders.length, live.status, nowMin === null ? -1 : Math.floor(nowMin / 15)]); // eslint-disable-line
  const usualSoFar = useMemo(() => {
    if (!o || nowMin === null) return null;
    const tot = o.curve_usual.reduce((a, p) => a + p.orders, 0);
    const so = o.curve_usual.reduce((a, p) => a + p.orders * Math.max(0, Math.min(1, (nowMin - toMin(p.time)) / 15)), 0);
    const usualNet = o.kpis && vs("net_sales") !== null ? o.kpis.net_sales / (1 + (vs("net_sales") as number)) : null;
    return { orders: so, net: usualNet !== null && tot ? (usualNet * so) / tot : null };
  }, [o, nowMin]); // eslint-disable-line
  const bins = useMemo(() => {
    const base = intra.data?.bins || [];
    if (!isLive || nowMin === null) return base;
    return binsFromFeed(live.orders, base, nowMin).filter((b) => toMin(b.time) <= nowMin);
  }, [isLive, intra.data, live.orders.length, nowMin]); // eslint-disable-line

  const k = o?.kpis;
  const net = tick ? tick.net_sales : k?.net_sales ?? 0;
  const orders = tick ? tick.orders : k?.orders ?? 0;
  const ticket = orders ? net / orders : 0;
  const netVs = tick ? (usualSoFar?.net ? net / usualSoFar.net - 1 : null) : vs("net_sales");
  const ordVs = tick ? (usualSoFar?.orders ? orders / usualSoFar.orders - 1 : null) : vs("orders");
  const tkVs = tick ? (usualSoFar?.net && usualSoFar.orders ? ticket / (usualSoFar.net / usualSoFar.orders) - 1 : null) : vs("avg_ticket");

  // channels: live ticks carry by_channel (money if it adds up to net sales, else order counts)
  const chan = useMemo(() => {
    if (!o) return [];
    const usual = Object.fromEntries(o.channels.map((c) => [c.key, c.usual]));
    if (tick) {
      const src = tick.by_channel_sales || tick.by_channel;
      const sum = CHANNELS.reduce((a, c) => a + (src[c] || 0), 0);
      const isMoney = !!tick.by_channel_sales || Math.abs(sum - tick.net_sales) <= Math.max(5, tick.net_sales * 0.05);
      const frac = usualSoFar?.orders && o.curve_usual.length ? usualSoFar.orders / o.curve_usual.reduce((a, p) => a + p.orders, 0) : 1;
      return CHANNELS.map((c) => ({ key: c, today: src[c] || 0, usual: isMoney ? (usual[c] || 0) * frac : null, money: isMoney }));
    }
    return CHANNELS.map((c) => ({ key: c, today: o.channels.find((x) => x.key === c)?.today ?? 0, usual: usual[c] ?? null, money: true }));
  }, [o, tick, usualSoFar]);
  const chanMax = Math.max(1, ...chan.map((c) => Math.max(c.today, c.usual || 0)));

  const soldLive = isLive && (live.status === "done" || live.events.some((e) => e.kind === "sold_out") || (tick?.chashu_left ?? 1) <= 0);
  const so = !isLive || soldLive ? day.data?.close?.sold_out || null : null;
  const startLeft = isLive ? Math.max(live.par ?? 0, 1) : so?.prepped ?? null;
  const left = tick ? tick.chashu_left : so ? 0 : null;
  const md = date ? fmtMonthDay(date) : "";

  const dayT: WhyTarget = { kind: "day", date };
  const openDay = (anchor: string) => why.open(dayT, anchor);
  const sel = why.target?.kind === "bin" && why.target.date === date ? why.target.time : null;
  // tonight's close unlocks at closing time; earlier nights can be (re)closed any time
  const locked = isToday && inService;
  const actions = locked
    ? <button className="btn" disabled aria-label="Close shift" title={`Tonight's close unlocks at ${clock(now!.close)}`}>Close shift<span className="unlock"> · unlocks {clock(now!.close)}</span></button>
    : <button className="btn" onClick={() => setOpen(true)} disabled={!o || closed}>Close shift</button>;
  return (
    <Page title="Tonight" actions={actions}>
      {ov.error && <ErrorBox error={ov.error} retry={ov.reload} />}
      {!o && !ov.error && <>
        <Skeleton h={330} />
        <div className="grid4">{[0, 1, 2, 3].map((i) => <Skeleton key={i} h={112} />)}</div>
      </>}
      {o && closed && (
        <section className="hero" style={{ gridTemplateColumns: "1fr" }}>
          <div><div className="lab">{dow}</div><div className="big">{o.not_open_yet ? "Not open yet" : "Closed"}</div>
            {o.not_open_yet && o.opens && <div className="ink2" style={{ marginTop: 6 }}>Opens at {clock(o.opens)}</div>}
            <div className="drv">{(o.context?.events || []).map((e) => <div key={e}><span>{e}</span></div>)}</div></div>
        </section>
      )}
      {o && !closed && k && <>
        <section className="hero tonight-hero" aria-label="Net sales"><Own a="analyst" dark />
          <div>
            <div className="lab">Net sales{tick ? ` · ${clock(tick.t)}` : ""}</div>
            <div className="big"><Tween value={net} fmt={(v) => money(v)} /></div>
            <div className="drv">
              <div><span>Vs usual {dow}{tick ? " so far" : ""}</span><b>{netVs === null ? "–" : pct(netVs, 1)}</b></div>
              <div><span>Orders</span><b><Tween value={orders} /></b></div>
              {o.context.rain && <div><span>Rain</span><b>Yes</b></div>}
              {o.context.events.filter((e) => !/sold out/i.test(e)).slice(0, 2).map((e) => <div key={e}><span>{e}</span><b /></div>)}
            </div>
          </div>
          <div>
            <div className="legend-inline"><span><i className="sw" style={{ background: "#b8e986" }} />{fmtMonthDay(date)}</span><span><i className="sw" style={{ background: "#8cc8ff" }} />Usual {dow}</span></div>
            <DayCurve today={isLive ? liveCurve : o.curve_today} usual={o.curve_usual} nowMin={nowMin} H={280}
              todayLabel={md} usualLabel={`Usual ${dow}`}
              onHover={(t) => why.prefetch({ kind: "bin", date, time: t })}
              onPick={(p) => why.open({ kind: "bin", date, time: p.time }, "tonight-top")} />
          </div>
        </section>

        <div className="grid4">
          <Kpi label="Orders" value={orders} vs={ordVs} onAsk={() => openDay("tonight-top")} onHover={() => why.prefetch(dayT)} />
          <Kpi label="Average ticket" value={ticket} fmt={(v) => money(v, 2)} vs={tkVs} onAsk={() => openDay("tonight-top")} onHover={() => why.prefetch(dayT)} />
          {tick
            ? <Kpi label="Cancels" value={tick.cancels} bad={tick.cancels > 0} onAsk={() => openDay("tonight-top")} onHover={() => why.prefetch(dayT)} />
            : <Kpi label="Labour" value={k.labour_pct} fmt={(v) => pct(v, 1, false)} vs={vs("labour_pct")} invert onAsk={() => openDay("tonight-top")} onHover={() => why.prefetch(dayT)} />}
          <Kpi label="Store-caused cancels" value={tick ? Math.min(tick.cancels, k.avoidable_cancels) : k.avoidable_cancels} bad={(tick ? Math.min(tick.cancels, k.avoidable_cancels) : k.avoidable_cancels) > 0}
            onAsk={() => openDay("tonight-top")} onHover={() => why.prefetch(dayT)} owner="guard" />
        </div>
        <WhySlot anchor="tonight-top" />

        <div className="tonight-grid">
          <div className="card">
            <div className="cardhead"><h3>{isLive ? "Orders" : "Items"}</h3>{isLive && <span className="ink2 num" style={{ fontSize: 14 }}>{live.orders.length} in</span>}</div>
            {isLive ? <Feed orders={live.orders} /> : <Items rows={items.data} loading={items.loading} onAsk={() => openDay("tonight-mid")} />}
          </div>
          <div className="card">
            <Own a="analyst" /><div className="cardhead"><h3>By channel</h3><span className="ink2" style={{ fontSize: 14 }}>{chan[0]?.money ? "Net sales" : "Orders"}</span></div>
            {chan.map((c) => (
              <button key={c.key} className="clickrow chanrow" data-why onMouseEnter={() => why.prefetch(dayT)} onClick={() => openDay("tonight-mid")}>
                <span style={{ width: 92 }}><i className="sw" style={{ background: CH_COLOR[c.key] }} />{appName[c.key]}</span>
                <span style={{ flex: 1 }}><HBar value={c.today} max={chanMax} color={CH_COLOR[c.key]} h={10} />
                  {c.usual !== null && <span className="usualmark" style={{ left: `${Math.min(100, (c.usual / chanMax) * 100)}%` }} />}</span>
                <b className="num" style={{ minWidth: 76, textAlign: "right" }}><Tween value={c.today} fmt={(v) => (c.money ? money(v) : Math.round(v).toString())} /></b>
                <span className={`num ${c.usual !== null && c.today < c.usual ? "crit" : "good"}`} style={{ minWidth: 58, textAlign: "right", fontSize: 13.5, fontWeight: 600 }}>
                  {c.usual ? pct(c.today / c.usual - 1, 0) : ""}</span>
              </button>
            ))}
          </div>
          <div className="card cream">
            <Own a="stock" /><div className="cardhead"><h3>Chashu</h3>{so && <span className="crit" style={{ fontSize: 14, fontWeight: 600 }}>{left === 0 || !isLive ? `Sold out ${clock(so.at)}` : ""}</span>}</div>
            <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
              <FoodIcon kind="chashu" size={46} />
              <div className="bignum">{left === null ? "–" : <Tween value={left} />}<span className="unit">left</span></div>
            </div>
            {startLeft !== null && left !== null && <div style={{ marginTop: 14 }}><HBar value={left} max={startLeft} color={left < 40 ? "#d03b3b" : "#0f4d40"} track="#ead9ad" h={12} /></div>}
            {so && <dl className="facts">
              <dt>Live on apps after sell-out</dt><dd>{so.minutes_live} min</dd>
              <dt>App cancels</dt><dd>{so.app_cancels}</dd>
              <dt>Prepped</dt><dd>{Math.round(so.prepped ?? 0)}</dd>
            </dl>}
            {isLive && live.events.length > 0 && <div className="evts">
              {[...live.events].reverse().slice(0, 4).map((e) => <div key={e.t + e.text} className="enter"><span className="num muted">{clock(e.t)}</span>{shortEvent(e)}</div>)}
            </div>}
          </div>
        </div>

        <WhySlot anchor="tonight-mid" />

        <div className="card">
          <Own a="analyst" /><div className="cardhead"><h3>Every 15 minutes</h3><ChannelLegend hidden={hidden} toggle={(c) => setHidden((h) => { const n = new Set(h); n.has(c) ? n.delete(c) : n.add(c); return n; })} /></div>
          {intra.error && !isLive ? <ErrorBox error={intra.error} retry={intra.reload} /> : !intra.data && !isLive ? <Skeleton h={260} /> :
            <StackedBins bins={bins} usual={intra.data?.usual} hidden={hidden} nowMin={nowMin} selected={sel}
              onHover={(b) => why.prefetch({ kind: "bin", date, time: b.time })}
              onPick={(b) => why.open({ kind: "bin", date, time: b.time }, "tonight-bins")} />}
          <WhySlot anchor="tonight-bins" />
        </div>
      </>}
      {o && !o.kpis && !closed && <SkeletonCard />}
      {open && o && <CloseModal date={date} onClose={() => setOpen(false)} onStarted={(r) => nav(`/close?run=${encodeURIComponent(r.run_id)}&date=${r.date}`)} items={store?.limited_items} />}
    </Page>
  );
}

function Kpi({ label, value, fmt, vs, bad, invert, onAsk, onHover, owner = "analyst" }: { owner?: "analyst" | "guard" | "books"; label: string; value: number; fmt?: (v: number) => string; vs?: number | null; bad?: boolean; invert?: boolean; onAsk: () => void; onHover?: () => void }) {
  const down = vs !== null && vs !== undefined && (invert ? vs > 0 : vs < 0);
  return (
    <button className="card kpi kpibtn" data-why onClick={onAsk} onMouseEnter={onHover}><Own a={owner} />
      <div className="l">{label}</div>
      <div className={`v${bad ? " crit" : ""}`}><Tween value={value} fmt={fmt} /></div>
      {vs !== undefined && <div className={`d${down ? " bad" : ""}`}>{vs === null ? " " : `${pct(vs, 1)} vs usual`}</div>}
    </button>
  );
}

function Feed({ orders }: { orders: LiveOrder[] }) {
  const last = orders.slice(-12).reverse();
  return (
    <div className="feed" aria-live="off" data-testid="feed">
      {last.map((o) => (
        <div key={o.id}>
          <span className="num muted">{clock(o.t.slice(0, 5))}</span>
          <i className="sw" style={{ background: CH_COLOR[o.channel], margin: 0 }} />
          <span style={{ overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap", color: /cancel/.test(o.status) ? "var(--crit)" : undefined }}>
            {o.items.join(", ")}</span>
          <b className="num">{money(o.subtotal, 2)}</b>
        </div>
      ))}
      {!last.length && Array.from({ length: 6 }, (_, i) => <span key={i} className="skeleton" style={{ minHeight: 18, margin: "6px 0" }} />)}
    </div>
  );
}

function Items({ rows, loading, onAsk }: { rows: { item: string; sold: number; net_sales: number; share: number }[] | null; loading: boolean; onAsk: () => void }) {
  if (loading) return <Skeleton h={280} />;
  if (!rows?.length) return <div className="ink2">–</div>;
  const top = [...rows].sort((a, b) => b.net_sales - a.net_sales).slice(0, 8);
  const max = Math.max(...top.map((r) => r.net_sales));
  return (
    <div>
      {top.map((r) => (
        <button key={r.item} className="clickrow" data-why onClick={onAsk} style={{ padding: "6px 10px" }}>
          <span style={{ width: 120, whiteSpace: "nowrap", overflow: "hidden", textOverflow: "ellipsis" }}>{r.item}</span>
          <span style={{ flex: 1 }}><HBar value={r.net_sales} max={max} /></span>
          <span className="num ink2" style={{ minWidth: 40, textAlign: "right", fontSize: 13.5 }}>{r.sold}</span>
          <b className="num" style={{ minWidth: 70, textAlign: "right" }}>{money(r.net_sales)}</b>
        </button>
      ))}
    </div>
  );
}

function CloseModal({ date, items, onClose, onStarted }: { date: string; items?: string[]; onClose: () => void; onStarted: (r: { run_id: string; date: string }) => void }) {
  const list = items?.length ? items : ["Chashu"];
  const [counts, setCounts] = useState<Record<string, number>>(Object.fromEntries(list.map((i) => [i, 0])));
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);
  const start = async () => {
    setBusy(true); setErr(null);
    try {
      const pc = Object.fromEntries(Object.entries(counts).map(([k, v]) => [k.toLowerCase(), Math.max(0, v)]));
      onStarted(await api.startClose({ date, portion_counts: pc, force: true }));
    } catch (e) { setErr(String((e as Error).message)); setBusy(false); }
  };
  return (
    <div className="scrim" onMouseDown={onClose}>
      <div className="modal" role="dialog" aria-modal="true" aria-labelledby="close-title" onMouseDown={(e) => e.stopPropagation()}
        onKeyDown={(e) => { if (e.key === "Escape") onClose(); if (e.key === "Enter") start(); }}>
        <h2 id="close-title">Close shift</h2>
        {list.map((it) => (
          <div className="stepper" key={it}>
            <FoodIcon kind="chashu" />
            <label htmlFor={`cnt-${it}`} style={{ fontWeight: 600 }}>{it} left</label>
            <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
              <button className="btn light small" aria-label="Fewer" onClick={() => setCounts((c) => ({ ...c, [it]: Math.max(0, c[it] - 1) }))}>−</button>
              <NumberField id={`cnt-${it}`} value={counts[it]} onChange={(v) => setCounts((c) => ({ ...c, [it]: v }))} style={{ width: 80, textAlign: "center" }} />
              <button className="btn light small" aria-label="More" onClick={() => setCounts((c) => ({ ...c, [it]: c[it] + 1 }))}>+</button>
            </div>
          </div>
        ))}
        {err && <ErrorBox error={err} />}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
          <button className="btn light" onClick={onClose}>Cancel</button>
          <button className="btn" onClick={start} disabled={busy}>{busy ? "Starting" : "Start the close"}</button>
        </div>
      </div>
    </div>
  );
}
