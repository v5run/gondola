/** Past › Summary: how a day went, in four numbers and three sentences. */
import { useEffect, useState } from "react";
import { tri, type DayReview, type PastSummary as PS } from "../api/tri";
import { Page } from "../components/Page";
import { CH_COLOR, ErrorBox, Skeleton, appName, money } from "../components/ui";
import { fmtDay } from "../lib/dates";
import { useApp } from "../state";

export default function PastSummary() {
  const { date } = useApp();
  const [s, setS] = useState<(PS & { sales?: number; promises_met_pct?: number; cancels_by_reason?: Record<string, number> }) | null>(null);
  const [rv, setRv] = useState<DayReview | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!date) return;
    let on = true;
    setS(null); setErr(null); setRv(null);
    tri.past.summary(date).then((x) => on && setS(x as any)).catch((e) => on && setErr(String(e.message)));
    tri.review.day(date).then((x) => on && setRv(x)).catch(() => {});
    return () => { on = false; };
  }, [date, n]);
  const chans = s ? Object.entries(s.by_channel || {}).sort((a, b) => b[1].orders - a[1].orders) : [];
  const maxO = Math.max(1, ...chans.map(([, v]) => v.orders));
  const onTime = s ? (s.promises_met_pct ?? (s.promises_total ? s.promises_met / s.promises_total : null)) : null;
  const unavailable = s?.cancels_by_reason?.item_unavailable || 0;
  return (
    <Page title="Past">
      {err && <ErrorBox error={err} retry={() => setN((x) => x + 1)} />}
      {!s && !err && <><Skeleton h={140} /><Skeleton h={260} /></>}
      {s && <>
        <section className="ps-nums">
          <div><span>Orders</span><b className="num">{s.processed.toLocaleString()}</b></div>
          <div><span>Sales</span><b className="num">{money(s.sales ?? chans.reduce((a, [, v]) => a + v.sales, 0))}</b></div>
          <div className={onTime !== null && onTime < 0.85 ? "warn" : ""}><span>On time</span><b className="num">{onTime === null ? "—" : `${Math.round(onTime * 100)}%`}</b><small>{s.promises_met} of {s.promises_total} orders</small></div>
          <div className={s.cancels >= 5 ? "warn" : ""}><span>Cancelled</span><b className="num">{s.cancels}</b>{unavailable > 0 && <small>{unavailable} because an item ran out</small>}</div>
        </section>
        <div className="ps-grid">
          <div className="card">
            <h3>{fmtDay(s.date)} — what stood out</h3>
            {!rv && <p className="ink2 ps-gap">No end-of-day review for this day yet.</p>}
            {rv && <ul className="ps-points">
              {rv.wrong.slice(0, 3).map((w) => <li key={w.text} className="pt-bad"><i aria-hidden>!</i>{w.text}</li>)}
              {rv.well.slice(0, 2).map((w) => <li key={w.text} className="pt-good"><i aria-hidden>✓</i>{w.text}</li>)}
            </ul>}
          </div>
          <div className="card">
            <h3>By app</h3>
            <ul className="ps-ch">
              {chans.map(([k, v]) => (
                <li key={k}><span>{appName[k] || k}</span>
                  <span className="ps-bar"><i style={{ width: `${(v.orders / maxO) * 100}%`, background: CH_COLOR[k] || "#888" }} /></span>
                  <b className="num">{v.orders}</b><span className="num ink2">{money(v.sales)}</span></li>
              ))}
            </ul>
          </div>
        </div>
      </>}
    </Page>
  );
}
