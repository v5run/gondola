import { useCallback, useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import type { DailyMetric, RangeMetrics } from "../api/types";
import { Page } from "../components/Page";
import { YearChart, type DayVal } from "../components/charts";
import { ErrorBox, Segmented, Skeleton, Tween, money, pct, useLoad } from "../components/ui";
import { addDays, daysBetween, fmtRange } from "../lib/dates";
import { useApp } from "../state";
import { WhySlot, useWhy } from "../why";
import { Own } from "../agents";

type Metric = "net_sales" | "orders";

export default function Insights() {
  const { store, date } = useApp();
  const why = useWhy();
  const [metric, setMetric] = useState<Metric>("net_sales");
  const daily = useLoad(() => (store ? api.metrics(store.first_date, store.today) : new Promise<never>(() => {})), [store?.today]);
  const days: (DayVal & { m?: DailyMetric })[] = useMemo(() => {
    if (!store || !daily.data) return [];
    const by = new Map(daily.data.map((d) => [d.date, d]));
    const n = daysBetween(store.first_date, store.today) + 1;
    return Array.from({ length: n }, (_, i) => {
      const d = addDays(store.first_date, i); const m = by.get(d);
      return { date: d, value: m ? m[metric] : 0, orders: m?.orders, closed: !m || m.orders === 0, m };
    });
  }, [store, daily.data, metric]);
  const [brush, setBrush] = useState<[number, number] | null>(null);
  const [final, setFinal] = useState<[number, number] | null>(null);
  const defaultBrush = useCallback((): [number, number] => {
    const end = Math.max(0, days.findIndex((d) => d.date === date));
    return [Math.max(0, end - 27), end];
  }, [days, date]);
  // first load, and keep the chosen date inside the brush
  useEffect(() => {
    if (!days.length) return;
    const i = days.findIndex((d) => d.date === date);
    setBrush((b) => {
      if (!b) { const nb = defaultBrush(); setFinal(nb); return nb; }
      if (i >= 0 && (i < b[0] || i > b[1])) { const len = b[1] - b[0]; const a = Math.max(0, i - len); const nb: [number, number] = [a, a + len]; setFinal(nb); return nb; }
      return b;
    });
  }, [days, date, defaultBrush]);

  const sel = brush && days.length ? { start: days[brush[0]].date, end: days[brush[1]].date } : null;
  const fin = final && days.length ? { start: days[final[0]].date, end: days[final[1]].date } : null;
  const range = useLoad<RangeMetrics | null>(() => (fin ? api.range(fin.start, fin.end) : Promise.resolve(null)), [fin?.start, fin?.end]);
  // a settled brush opens its breakdown under the chart (or swaps the pinned window)
  useEffect(() => { if (fin) why.open({ kind: "range", start: fin.start, end: fin.end }, "insights"); }, [fin?.start, fin?.end]); // eslint-disable-line
  // instant numbers while dragging, from the daily series
  const local = useMemo(() => {
    if (!brush) return null;
    const s = days.slice(brush[0], brush[1] + 1).filter((d) => d.m);
    const ns = s.reduce((a, d) => a + (d.m!.net_sales || 0), 0), or = s.reduce((a, d) => a + (d.m!.orders || 0), 0);
    return { net_sales: ns, orders: or, avg_ticket: or ? ns / or : 0, days: brush[1] - brush[0] + 1,
      cancels: s.reduce((a, d) => a + d.m!.avoidable_cancels, 0), labour_pct: s.length ? s.reduce((a, d) => a + d.m!.labour_pct * d.m!.net_sales, 0) / Math.max(1, ns) : 0 };
  }, [brush, days]);
  const settled = !!range.data && !!sel && range.data.start === sel.start && range.data.end === sel.end;
  const r = settled ? range.data! : null;
  const label = sel ? fmtRange(sel.start, sel.end) : "";
  const picked = why.target?.kind === "day" ? why.target.date : null;

  return (
    <Page title="Insights">
      {daily.error && <ErrorBox error={daily.error} retry={daily.reload} />}
      <div className="grid5">
        <RangeKpi label="Average ticket" v={r ? r.avg_ticket : local?.avg_ticket} fmt={(v) => money(v, 2)} pending={!settled} />
        <RangeKpi label="Labour" v={r ? r.labour_pct : local?.labour_pct} fmt={(v) => pct(v, 1, false)} pending={!settled} />
        <RangeKpi label="Cancels" v={r ? r.cancels : undefined} pending={!settled} />
        <RangeKpi label="Store-caused cancels" v={r ? r.avoidable_cancels : local?.cancels} pending={!settled} bad />
        <RangeKpi label="Open days" v={r ? ((r as RangeMetrics & { open_days?: number }).open_days ?? r.days) : local?.days} pending={!settled} />
      </div>

      <div className="card">
        <div className="cardhead">
          <div className="rangehead">
            <h3>{label}</h3>
            {local && <><span className="num">{local.days} days</span><span className="num"><Tween value={local.net_sales} fmt={(v) => money(v)} ms={160} /></span><span className="num"><Tween value={local.orders} ms={160} /> orders</span></>}
          </div>
          <div style={{ display: "flex", gap: 10, alignItems: "center" }}>
            <Segmented label="Metric" value={metric} onChange={setMetric} options={[["net_sales", "Net sales"], ["orders", "Orders"]]} />
          </div>
        </div>
        {!days.length ? <Skeleton h={230} /> :
          <YearChart days={days} brush={brush || [0, 0]} selected={date} picked={picked} onHoverDay={(d) => why.prefetch({ kind: "day", date: d.date })} fmt={(v) => (metric === "net_sales" ? money(v) : `${Math.round(v)} orders`)}
            onBrush={(a, b, f) => { setBrush([a, b]); if (f) setFinal([a, b]); }}
            onReset={() => { const b = defaultBrush(); setBrush(b); setFinal(b); }}
            onPickDay={(d) => { if (!d.closed) why.open({ kind: "day", date: d.date }, "insights"); }} />}
        <WhySlot anchor="insights" />
      </div>

    </Page>
  );
}

function RangeKpi({ label, v, fmt, vs, pending, bad }: { label: string; v?: number; fmt?: (v: number) => string; vs?: number | null; pending?: boolean; bad?: boolean }) {
  return (
    <div className="card kpi">
      <Own a="analyst" /><div className="l">{label}</div>
      <div className={`v${bad && v ? " crit" : ""}`}><Tween value={v ?? null} fmt={fmt} ms={180} /></div>
      <div className={`d${(vs ?? 0) < 0 ? " bad" : ""}`} style={{ visibility: vs === undefined || vs === null || pending ? "hidden" : undefined }}>{pct(vs ?? 0, 1)} vs the period before</div>
    </div>
  );
}

