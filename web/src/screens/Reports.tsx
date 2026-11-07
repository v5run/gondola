import { useEffect, useMemo, useState } from "react";
import { api, reportPaths } from "../api/client";
import type { ReportEntry } from "../api/types";
import { Page } from "../components/Page";
import { ErrorBox, Icon, Segmented, Skeleton, Tween, compactMoney, money, pct, shortDate, useLoad } from "../components/ui";
import { D, addDays, fmtMonth, fmtMonthDay, iso } from "../lib/dates";
import { useApp, useToast } from "../state";
import { Own } from "../agents";

type Filter = "all" | "texted" | "urgent";
/** Diverging scale for net sales vs usual: two hues and a neutral middle, five discrete steps. */
const HEAT = [[-0.12, "#d03b3b"], [-0.04, "#f2b8ae"], [0.04, "#e4e2da"], [0.12, "#c4e89c"], [Infinity, "#0f4d40"]] as const;
const heat = (v: number | null | undefined) => (v === null || v === undefined ? "#ecebe5" : HEAT.find(([k]) => v < k)![1]);
const darkCell = (v: number | null | undefined) => v !== null && v !== undefined && (v < -0.12 || v >= 0.12);

export default function Reports() {
  const { date, setDate } = useApp();
  const toast = useToast();
  const list = useLoad(() => api.reports(), []);
  const [entries, setEntries] = useState<ReportEntry[]>([]);
  useEffect(() => { if (list.data) setEntries(list.data); }, [list.data]);
  const [filter, setFilter] = useState<Filter>("all");
  const [month, setMonth] = useState("all");
  const [q, setQ] = useState("");
  const [sel, setSel] = useState<{ date: string; kind: "daily" | "monthly" } | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [frameKey, setFrameKey] = useState(0);
  const daily = entries.filter((r) => r.kind === "daily");
  const monthly = entries.filter((r) => r.kind === "monthly");
  const byDate = useMemo(() => new Map(daily.map((r) => [r.date, r])), [daily]);
  const months = useMemo(() => Array.from(new Set(daily.map((r) => r.date.slice(0, 7)))).sort().reverse(), [daily]);

  // the global date picks the matching nightly report
  useEffect(() => {
    if (!entries.length) return;
    if (byDate.has(date)) setSel({ date, kind: "daily" });
    else if (!sel) setSel(daily[0] ? { date: daily[0].date, kind: "daily" } : null);
  }, [date, entries.length]); // eslint-disable-line
  const cur = sel ? entries.find((r) => r.date === sel.date && r.kind === sel.kind) || null : null;
  const pick = (r: ReportEntry) => { setSel({ date: r.date, kind: r.kind }); if (r.kind === "daily") setDate(r.date); };

  const shown = daily.filter((r) => (filter === "all" || (filter === "texted" ? r.texted : (r.urgent || 0) > 0))
    && (month === "all" || r.date.startsWith(month))
    && (!q.trim() || `${r.headline || ""} ${shortDate(r.date)} ${r.date}`.toLowerCase().includes(q.trim().toLowerCase())));

  const rebuild = async (r: ReportEntry) => {
    setBusy(r.date);
    try {
      await api.rebuild(r);
      setEntries((es) => es.map((x) => (x.date === r.date && x.kind === r.kind ? { ...x, status: "rebuilt" } : x)));
      setSel({ date: r.date, kind: r.kind }); setFrameKey((k) => k + 1);
      toast(`${r.kind === "daily" ? shortDate(r.date) : fmtMonth(r.date)} rebuilt`, "good");
    } catch (e) { toast(String((e as Error).message), "crit"); }
    finally { setBusy(null); }
  };

  // calendar: the last 13 weeks ending at the newest report, Sunday-aligned columns
  const last = daily[0]?.date || date;
  const first = daily.length ? daily[daily.length - 1].date : addDays(last, -90);
  const startCal = useMemo(() => {
    const lo = first > addDays(last, -7 * 15 + 1) ? first : addDays(last, -7 * 15 + 1);
    const s = D(lo); s.setDate(s.getDate() - s.getDay()); return iso(s);
  }, [first, last]);
  const cal = useMemo(() => { const out: string[] = []; for (let d = startCal; d <= last; d = addDays(d, 1)) out.push(d); return out; }, [startCal, last]);
  const inCal = daily.filter((r) => r.date >= startCal);
  const sum = (f: (r: ReportEntry) => number) => inCal.reduce((a, r) => a + f(r), 0);

  return (
    <Page title="Reports">
      {list.error && <ErrorBox error={list.error} retry={list.reload} />}
      <div className="reports-top">
        <div className="card">
          <div className="cardhead">
            <h3>{cal.length ? `${fmtMonthDay(startCal)} – ${fmtMonthDay(last)}` : "Nights"}</h3>
            <div className="heatkey"><span>Below usual</span>{HEAT.map(([, c]) => <i key={c} style={{ background: c }} />)}<span>Above</span>
              <span><b className="mk urgent" />Urgent</span><span><b className="mk texted" />Texted</span><span><b className="mk expired" />Expired</span></div>
          </div>
          {!list.data ? <Skeleton h={190} /> : (
            <div className="heatwrap">
              <div className="heatdays ink2">{["", "", "Mon", "", "Wed", "", "Fri", ""].map((d, i) => <span key={i}>{d}</span>)}</div>
              <div>
                <div className="heatmonths ink2" style={{ gridTemplateColumns: `repeat(${Math.ceil(cal.length / 7)}, var(--cell))` }}>
                  {Array.from({ length: Math.ceil(cal.length / 7) }, (_, w) => { const d = cal[w * 7]; const show = w === 0 || d.slice(5, 7) !== cal[(w - 1) * 7].slice(5, 7); return <span key={w}>{show ? D(d).toLocaleDateString("en-US", { month: "short" }) : ""}</span>; })}
                </div>
                <div className="heat" style={{ gridTemplateColumns: `repeat(${Math.ceil(cal.length / 7)}, var(--cell))` }} data-testid="heatmap">
                  {cal.map((d) => {
                    const r = byDate.get(d);
                    return (
                      <button key={d} disabled={!r} onClick={() => r && pick(r)} className={sel?.date === d && sel.kind === "daily" ? "sel" : ""}
                        style={{ background: r ? heat(r.vs_usual_pct) : "transparent", color: darkCell(r?.vs_usual_pct) ? "#fff" : "var(--ink2)" }}
                        title={r ? `${shortDate(d)} · ${money(r.net_sales)} · ${pct(r.vs_usual_pct ?? null, 0)} vs usual` : shortDate(d)} data-date={d}>
                        {r ? Number(d.slice(8)) : ""}
                        {r && (r.urgent || 0) > 0 && <b className="mk urgent" />}
                        {r?.texted && <b className="mk texted" style={{ right: "auto", left: 3 }} />}
                        {r?.status === "expired" && <b className="mk expired" />}
                      </button>
                    );
                  })}
                </div>
              </div>
            </div>
          )}
        </div>
        <div className="grid2 rstats">
          <div className="card kpi"><Own a="report" /><div className="l">Nights</div><div className="v"><Tween value={inCal.length} /></div></div>
          <div className="card kpi"><Own a="analyst" /><div className="l">Net sales</div><div className="v"><Tween value={sum((r) => r.net_sales || 0)} fmt={(v) => (v >= 1e6 ? `$${(v / 1e6).toFixed(2)}M` : compactMoney(v))} /></div></div>
          <div className="card kpi"><Own a="sentinel" /><div className="l">Texted</div><div className="v"><Tween value={inCal.filter((r) => r.texted).length} /></div></div>
          <div className="card kpi cream"><Own a="books" /><div className="l">Recoverable</div><div className="v"><Tween value={sum((r) => r.recoverable_usd || 0)} fmt={(v) => money(v)} /></div></div>
        </div>
      </div>

      {monthly.length > 0 && (
        <div className="months">
          {monthly.map((m) => (
            <button key={m.date} className={`card monthcard${cur === m ? " on" : ""}`} onClick={() => pick(m)} data-testid="monthly">
              <b>{fmtMonth(m.date)}</b>
              <span className="num">{m.net_sales ? money(m.net_sales) : ""}{m.orders ? ` · ${m.orders.toLocaleString()} orders` : ""}</span>
              {m.status === "expired" && <span className="ink2">Expired</span>}
            </button>
          ))}
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "460px 1fr", gap: 22, alignItems: "start" }}>
        <div className="card rlist">
          <div className="rfilters">
            <Segmented label="Filter" value={filter} onChange={setFilter} options={[["all", "All"], ["texted", "Texted"], ["urgent", "Urgent"]]} />
            <select className="input slim" aria-label="Month" value={month} onChange={(e) => setMonth(e.target.value)} style={{ background: "var(--bg)" }}>
              <option value="all">All months</option>
              {months.map((m) => <option key={m} value={m}>{fmtMonth(m)}</option>)}
            </select>
          </div>
          <label className="search"><Icon name="search" size={18} /><input aria-label="Search reports" placeholder="Search" value={q} onChange={(e) => setQ(e.target.value)} /></label>
          <div className="rrows" data-testid="report-list">
            {!list.data && Array.from({ length: 6 }, (_, i) => <Skeleton key={i} h={58} />)}
            {list.data && !shown.length && <div className="empty">No nights match</div>}
            {shown.map((r) => (
              <div key={r.date} className={`rrow${cur === r ? " on" : ""}`} onClick={() => pick(r)} role="button" tabIndex={0} onKeyDown={(e) => e.key === "Enter" && pick(r)} data-date={r.date}>
                <div className="rrow-a">
                  <b>{shortDate(r.date)}</b>
                  <span className="num">{money(r.net_sales)}<span className={(r.vs_usual_pct ?? 0) < 0 ? "crit" : "good"}> {pct(r.vs_usual_pct ?? null, 0)}</span></span>
                </div>
                <div className="rrow-h">{r.headline}</div>
                <div className="rrow-m ink2 num">
                  <span>{r.orders} orders</span>
                  {(r.urgent || 0) > 0 && <span className="crit">{r.urgent} urgent</span>}
                  {(r.recoverable_usd || 0) > 0 && <span>{money(r.recoverable_usd, 0)} recoverable</span>}
                  {r.texted && <span>Texted</span>}
                  {r.status === "expired"
                    ? <button className="link rebuild" disabled={busy === r.date} onClick={(e) => { e.stopPropagation(); rebuild(r); }}>{busy === r.date ? "Rebuilding" : "Rebuild"}</button>
                    : r.status === "rebuilt" ? <span>Rebuilt</span> : null}
                </div>
              </div>
            ))}
          </div>
        </div>

        <div style={{ display: "flex", flexDirection: "column", gap: 12, minWidth: 0 }}>
          {cur && (
            <div className="cardhead" style={{ margin: 0 }}>
              <h3 style={{ fontSize: 18 }}>{cur.kind === "daily" ? shortDate(cur.date) : fmtMonth(cur.date)}{cur.status === "rebuilt" ? <span className="ink2" style={{ fontWeight: 500 }}> · rebuilt</span> : null}</h3>
              <div style={{ display: "flex", gap: 8 }}>
                {cur.status === "expired" && <button className="btn small" onClick={() => rebuild(cur)} disabled={busy === cur.date}>{busy === cur.date ? "Rebuilding" : "Rebuild"}</button>}
                <a className="btn small light" href={reportPaths(cur).pdf} target="_blank" rel="noreferrer">Open PDF</a>
              </div>
            </div>
          )}
          <div className="card viewer"><Own a="report" />
            {!cur ? <div className="empty">{list.data && !entries.length ? "No reports" : ""}</div>
              : cur.status === "expired" && busy !== cur.date ? (
                <div className="expired-view">
                  <b>Expired</b>
                  <button className="btn" onClick={() => rebuild(cur)}>Rebuild</button>
                </div>)
                : busy === cur.date ? <div style={{ padding: 30, display: "flex", flexDirection: "column", gap: 14 }}><Skeleton h={60} /><Skeleton h={300} /><Skeleton h={200} /></div>
                  : <iframe key={`${cur.kind}${cur.date}${frameKey}`} title={`Report ${cur.date}`} src={reportPaths(cur).html} />}
          </div>
        </div>
      </div>
    </Page>
  );
}
