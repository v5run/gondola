/** Future › Today: what kind of day is coming, in facts a busy manager can read in seconds. */
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import { tri, type FutureToday as FT, type LimitedItem } from "../api/tri";
import { Page } from "../components/Page";
import { ErrorBox, Skeleton } from "../components/ui";
import { fmtDay } from "../lib/dates";
import { useApp } from "../state";
import { usePlayback } from "../playback";

const ampm = (t?: string | null) => {
  if (!t) return "";
  const [h, m] = t.slice(0, 5).split(":").map(Number);
  return `${((h + 11) % 12) + 1}${m ? `:${String(m).padStart(2, "0")}` : ""} ${h >= 12 ? "pm" : "am"}`;
};
const pctTxt = (f: number) => `${f >= 0 ? "+" : "−"}${Math.abs(Math.round(f * 100))}%`;

export default function FutureToday() {
  const { now, inService, setDate } = useApp();
  const playback = usePlayback();
  const nav = useNavigate();
  const today = now?.today || "";
  const [t, setT] = useState<FT | null>(null);
  const [items, setItems] = useState<LimitedItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!today || playback.active) return;
    let dead = false;
    const pull = () => {
      tri.future.today(today).then((x) => !dead && (setT(x), setErr(null))).catch((e) => !dead && setErr(String(e.message)));
      tri.future.items(today).then((x) => !dead && setItems(x.items)).catch(() => {});
    };
    pull();
    const id = inService ? setInterval(pull, 60000) : undefined;
    return () => { dead = true; if (id) clearInterval(id); };
  }, [today, inService, n, playback.active]);
  const f = (playback.active ? playback.frame?.forecast : t) as (FT & { rush?: { start: string; end: string; peak_per_15min?: number }; similar_days?: { date: string; orders: number; why: string }[]; closed?: boolean }) | null | undefined;
  const its = playback.active ? playback.frame?.items : items;
  const sf = f?.so_far;
  const closed = !!f?.closed || (now?.phase === "closed" && !playback.active);
  const drivers = [...(f?.drivers || [])].sort((a, b) => Math.abs(b.effect_pct) - Math.abs(a.effect_pct));
  const events = drivers.filter((d) => d.kind !== "weekday" && d.kind !== "trend");
  const background = drivers.filter((d) => d.kind === "weekday" || d.kind === "trend");
  const outs = (its || []).filter((i) => i.projected_runout);

  return (
    <Page title="Future" date={false}>
      {err && <ErrorBox error={err} retry={() => setN((x) => x + 1)} />}
      {!f && !err && <><Skeleton h={150} /><Skeleton h={300} /></>}
      {f && <>
        <section className="ft-hero">
          <div>
            <span className="ft-lab">{fmtDay(f.date)} · {closed ? "orders (day is over)" : "expected orders"}</span>
            <b className="ft-big num">{Math.round(f.expected.p50)}</b>
            {!closed && Math.round(f.expected.p10) !== Math.round(f.expected.p90) && <span className="ft-rng num">usually between {Math.round(f.expected.p10)} and {Math.round(f.expected.p90)}</span>}
          </div>
          {sf && !closed && <div>
            <span className="ft-lab">So far</span>
            <b className="ft-mid num">{sf.orders}</b>
            {sf.vs_expected_pct !== null && <span className={`ft-rng ${Math.abs(sf.vs_expected_pct) >= 0.1 ? "warn" : ""}`}>{Math.abs(sf.vs_expected_pct) < 0.05 ? "right on pace" : `${Math.round(Math.abs(sf.vs_expected_pct) * 100)}% ${sf.vs_expected_pct > 0 ? "busier" : "quieter"} than expected by now`}</span>}
          </div>}
          {f.rush && <div>
            <span className="ft-lab">Busiest time</span>
            <b className="ft-mid">{ampm(f.rush.start)}–{ampm(f.rush.end)}</b>
            {f.rush.peak_per_15min && <span className="ft-rng num">about {Math.round(f.rush.peak_per_15min)} orders every 15 min</span>}
          </div>}
        </section>

        <div className="ft-grid">
          <div className="card">
            <h3>{closed ? "What shaped today" : "What's happening today"}</h3>
            {events.length === 0 && <p className="ink2 ft-gap">No events or weather that usually change business.</p>}
            <ul className="ft-facts">
              {events.map((d) => (
                <li key={d.label}>
                  <span className={`ft-ic k-${d.kind}`}>{d.time ? ampm(d.time) : "All day"}</span>
                  <div>
                    <b>{d.label}</b>
                    <span>{d.why}</span>
                    {d.channel_note && <span className="ft-note">{d.channel_note}</span>}
                  </div>
                  <span className={`ft-eff num ${d.effect_pct >= 0 ? "up" : "down"}`}>{pctTxt(d.effect_pct)}<small>orders</small></span>
                </li>
              ))}
            </ul>
            {background.length > 0 && <p className="ft-bg">{background.map((d) => `${d.label}: ${pctTxt(d.effect_pct)}`).join(" · ")}</p>}
          </div>

          <div className="ft-side">
            <div className="card cream">
              <h3>Might run out</h3>
              {!its && <Skeleton h={80} />}
              {its && outs.length === 0 && <p className="ft-gap">{closed ? "Service is over. Tomorrow’s prep is on the Tomorrow tab." : "Enough of every limited item for today."}</p>}
              <ul className="ft-outs">
                {outs.map((i) => <li key={i.key}><b>{i.name}</b><span className="num">around {ampm(i.projected_runout)}</span></li>)}
              </ul>
              {its && outs.length > 0 && <p className="ink2 ft-small">Gondola will pause it on the delivery apps before it runs out.</p>}
            </div>
            {!!f.similar_days?.length && <div className="card">
              <h3>Days like today</h3>
              <ul className="ft-sim">
                {f.similar_days.slice(0, 4).map((s) => (
                  <li key={s.date}><button onClick={() => { setDate(s.date); nav("/past"); }}>
                    <b>{fmtDay(s.date)}</b><span className="num">{s.orders} orders</span><small>{s.why}</small>
                  </button></li>
                ))}
              </ul>
            </div>}
          </div>
        </div>
      </>}
    </Page>
  );
}
