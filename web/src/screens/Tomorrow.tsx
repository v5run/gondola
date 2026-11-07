import { useEffect, useMemo, useState } from "react";
import { api } from "../api/client";
import { tri, type DayCard, type FutureDay } from "../api/tri";
import type { CardItem, Point } from "../api/types";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { DriverList } from "../components/future";
import { PauseCell, PrepCurve } from "../components/prep";
import { ErrorBox, NumberField, Skeleton, appName, clock, shortDate } from "../components/ui";
import { addDays, dowName } from "../lib/dates";
import { pauseTimes } from "../lib/plan";
import { useApp, useToast } from "../state";
import { Own, useAgents } from "../agents";
import { OutlookPanel } from "../components/OutlookPanel";

const APPS = ["doordash", "ubereats", "grubhub"] as const;

/** Future › Tomorrow: forward only (never a past day). Tomorrow's prep card is approved here. */
export default function Tomorrow() {
  const { now } = useApp();
  const toast = useToast();
  const { pulse } = useAgents();
  const today = now?.today || "";
  const start = today ? addDays(today, 1) : "";
  const [days, setDays] = useState<FutureDay[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [cards, setCards] = useState<Record<string, DayCard[]>>({});
  const [itemK, setItemK] = useState(0);
  const [shape, setShape] = useState<{ p50: number; curve: Point[] } | null>(null);
  const [approved, setApproved] = useState(false);
  const [saving, setSaving] = useState(false);
  const [refresh, setRefresh] = useState(0);
  useEffect(() => {
    if (!start) return;
    tri.future.days(start, 1).then((d) => { setDays(d.filter((x) => x.date >= start).slice(0, 1)); setErr(null); }).catch((e) => setErr(String(e.message)));
    // tomorrow's 15-minute curve gives the shape; other days scale it to their own expected orders
    api.forecast(start).then((f) => setShape({ p50: f.p50, curve: f.curve })).catch(() => setShape(null));
    api.close(today).then((c) => setApproved(!!c?.approved)).catch(() => {});
  }, [start, today, refresh]);
  const day = days?.[0] || null;
  const list = day ? cards[day.date] || day.cards : [];
  const card = list[Math.min(itemK, list.length - 1)];
  const curve = useMemo(() => (day?.curve?.length ? day.curve : day && shape ? shape.curve.map((p) => ({ ...p, orders: (p.orders * day.p50) / Math.max(1, shape.p50) })) : []), [day, shape]);
  const busy = useMemo(() => (day ? curve.map((p) => ({ ...p, orders: (p.orders * day.p90 * 1.1) / Math.max(1, day.p50) })) : []), [curve, day]);
  const ppoOf = (c: DayCard) => c.per_order || (day && day.p50 ? Math.max(0.01, c.target / day.p50) : 1);
  const timesOf = (c: DayCard) => {
    if (!curve.length || (day && !cards[day.date])) return { pz: c.pause_at, pzb: c.pause_if_busy };
    const have = c.prep + (c.on_hand || 0), ppo = ppoOf(c);
    return { pz: pauseTimes(curve, have, ppo, c.buffer ?? 8), pzb: pauseTimes(busy, have, ppo, c.buffer ?? 8) };
  };
  const setPrep = (k: number, v: number) => {
    if (!day) return;
    setCards((m) => ({ ...m, [day.date]: (m[day.date] || day.cards).map((c, j) => (j === k ? { ...c, prep: Math.max(0, Math.round(v)) } : c)) }));
  };
  const lock = approved;
  const approve = async () => {
    if (!day) return;
    setSaving(true);
    try {
      const out: CardItem[] = list.map((c) => { const t = timesOf(c); return { item: c.item, target: c.target, on_hand: c.on_hand, prep: c.prep, recount_at: Number(c.recount_at) || 0,
        pause_at: { doordash: t.pz.doordash ?? null, ubereats: t.pz.ubereats ?? null, grubhub: t.pz.grubhub ?? null },
        pause_if_busy: { doordash: t.pzb.doordash ?? null, ubereats: t.pzb.ubereats ?? null, grubhub: t.pzb.grubhub ?? null } }; });
      await api.approve(today, out);
      setApproved(true);
      pulse("forecaster", `${dowName(day.date)}'s prep approved`); setTimeout(() => pulse("controller", `pause times armed for ${dowName(day.date)}`), 250);
      toast(`${dowName(day.date)}'s prep approved`, "good");
    } catch (e) { toast(`Couldn't approve: ${(e as Error).message}`, "crit"); }
    finally { setSaving(false); }
  };
  const actions = day ? <>
    {approved && <button className="btn light" onClick={() => setApproved(false)}>Edit</button>}
    <button className="btn" onClick={approve} disabled={approved || saving || !list.length} data-testid="approve-prep">{approved ? "Approved" : saving ? "Approving" : `Approve ${dowName(day.date)}'s prep`}</button>
  </> : null;
  return (
    <Page title="Future" date={false} live={false} actions={actions}>
      <OutlookPanel date={start} onUpdate={() => { setCards({}); setRefresh((x) => x + 1); }} />
      {err && <ErrorBox error={err} />}
      {!days && !err && <Skeleton h={330} />}
      {day && <section className="hero tonight-hero" aria-label={`Forecast for ${day.date}`}><Own a="forecaster" dark /><Info k="day_forecast" dark />
        <div>
          <div className="lab">{shortDate(day.date)} · expected orders</div>
          <div className="big" data-testid="day-p50">{Math.round(day.p50)}<span className="num rng">{Math.round(day.p10)}–{Math.round(day.p90)}</span></div>
          <div className="drv">
            {day.rush && <div><span>Rush</span><b>{clock(day.rush.start)}–{clock(day.rush.end)}</b></div>}
            <div><span>Weather</span><b>{day.weather_known ? "Forecast" : "Typical for the date"}</b></div>
            {card && <div><span>{card.item}</span><b className="num">{Math.round(card.prep + (card.on_hand || 0))} {card.unit || ""}</b></div>}
          </div>
        </div>
        <div>
          <div className="legend-inline"><span><i className="sw" style={{ background: "#b8e986" }} />Expected</span><span><i className="sw" style={{ background: "#8cc8ff" }} />Busy night</span>{card && <span><i className="sw" style={{ background: "#fbf0d6" }} />Pause</span>}</div>
          {curve.length && card ? <PrepCurve curve={curve} busy={busy} have={card.prep + (card.on_hand || 0)} ppo={ppoOf(card)} pause={timesOf(card).pz as Record<string, string | null>} disabled={lock}
            item={card.item.toLowerCase()} step={card.batch || 10} H={280}
            onHave={(h) => setPrep(Math.min(itemK, list.length - 1), Math.max(0, Math.ceil((h - (card.on_hand || 0)) / (card.batch || 10)) * (card.batch || 10)))} />
            : <Skeleton h={280} />}
        </div>
      </section>}

      {day && <div className="days-grid">
        <div className="card"><Own a="forecaster" /><Info k="prep_card" />
          <div className="cardhead"><h3>Prep</h3></div>
          <div className="prepcards" data-testid="prep-cards">
            {list.map((c, k) => {
              const t = timesOf(c);
              const on = k === Math.min(itemK, list.length - 1);
              return (
                <div key={c.item} className={`prepc${on ? " on" : ""}`} onClick={() => setItemK(k)} data-item={c.item}>
                  <div className="pc-name"><b>{c.item}</b><span className="ink2 num">Target {Math.round(c.target)} · on hand {Math.round(c.on_hand)} · recount at {c.recount_at ?? "–"}</span></div>
                  <div className="pc-make">
                    <input type="range" className="range light" aria-label={`${c.item} prep`} min={0} max={Math.max(c.batch || 10, Math.ceil((c.target * 1.5) / (c.batch || 10)) * (c.batch || 10))} step={c.batch || 10}
                      value={c.prep} disabled={lock} onChange={(e) => setPrep(k, Number(e.target.value))} onFocus={() => setItemK(k)} />
                    <NumberField value={c.prep} step={c.batch || 10} onChange={(v) => setPrep(k, v)} disabled={lock} label={`${c.item} make`} style={{ width: 92, fontSize: 20, fontWeight: 700, textAlign: "right" }} />
                    <span className="ink2 pc-unit">{c.unit || ""}</span>
                  </div>
                  <div className="pc-pz">
                    {APPS.map((a) => <span key={a} data-app={a}><span className="ink2">{appName[a]}</span> <PauseCell t={t.pz[a] ?? null} /><span className="muted"> · busy {t.pzb[a] ? clock(t.pzb[a]!) : "–"}</span></span>)}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="card"><Own a="forecaster" /><Info k="drivers" />
          <div className="cardhead"><h3>Why</h3></div>
          <DriverList drivers={day.drivers} testid="day-drivers" />
        </div>
      </div>}
    </Page>
  );
}
