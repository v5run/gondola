import { useEffect, useMemo, useRef, useState } from "react";
import { api } from "../api/client";
import type { CardItem, Point } from "../api/types";
import { Page } from "../components/Page";
import { useWidth } from "../components/charts";
import { ErrorBox, FoodIcon, NumberField, Skeleton, Tween, appName, clock, shortDate, useLoad } from "../components/ui";
import { addDays, dowName, fmtMonthDay, fromMin, toMin } from "../lib/dates";
import { FALLBACK_PPO, PAUSE_DELAY, pauseTimes, portionsUntil, runOutMin } from "../lib/plan";
import { useApp, useToast } from "../state";
import { Own, useAgents } from "../agents";
import { useWhy, WhySlot } from "../why";

const APPS = ["doordash", "ubereats", "grubhub"] as const;

export default function Tomorrow() {
  const { date } = useApp();
  const toast = useToast();
  const why = useWhy();
  const { pulse } = useAgents();
  const next = date ? addDays(date, 1) : "";
  const fc = useLoad(() => (next ? api.forecast(next) : new Promise<never>(() => {})), [next]);
  const cl = useLoad(() => (date ? api.close(date).catch(() => null) : new Promise<never>(() => {})), [date]);
  const [card, setCard] = useState<CardItem[]>([]);
  const [approved, setApproved] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => { setCard(cl.data?.card || []); setApproved(!!cl.data?.approved); }, [cl.data]);
  const f = fc.data && fc.data.date === next ? fc.data : null;
  const dow = next ? dowName(next) : "Tomorrow";
  const c0 = card[0];
  const ppo = c0?.portions_per_order ?? cl.data?.portions_per_order ?? FALLBACK_PPO;
  const busyRatio = f && f.p50 ? (f.p90 / f.p50) * 1.1 : 1.2;
  const busy = useMemo(() => (f ? f.curve.map((p) => ({ ...p, orders: p.orders * busyRatio })) : []), [f, busyRatio]);
  const have = c0 ? c0.prep + (c0.on_hand || 0) : 0;
  const pz = useMemo(() => (f && c0 ? pauseTimes(f.curve, have, ppo) : null), [f, c0, have, ppo]);
  const pzBusy = useMemo(() => (f && c0 ? pauseTimes(busy, have, ppo) : null), [busy, f, c0, have, ppo]);
  const setPrep = (v: number) => setCard((cc) => cc.map((x, j) => (j === 0 ? { ...x, prep: Math.max(0, Math.round(v)) } : x)));
  const edited = !!cl.data?.card?.[0] && c0 && cl.data.card[0].prep !== c0.prep;

  const approve = async () => {
    if (!date || !card.length) return;
    const prev = approved;
    setApproved(true); setSaving(true); // optimistic
    try {
      const withTimes = card.map((c, i) => (i === 0 && pz && pzBusy ? { ...c, pause_at: pz, pause_if_busy: pzBusy } : c));
      const r = await api.approve(date, withTimes);
      setCard(r.card); pulse("plan", `${dow}'s plan approved`); setTimeout(() => pulse("guard", `armed for ${dow}`), 250); toast(`${dow}'s plan approved · ${r.card[0]?.prep ?? ""} chashu`, "good");
    } catch (e) {
      setApproved(prev); toast(`Couldn't approve: ${(e as Error).message}`, "crit");
    } finally { setSaving(false); }
  };

  const actions = <>
    {approved && <button className="btn light" onClick={() => setApproved(false)}>Edit plan</button>}
    <button className="btn" onClick={approve} disabled={!card.length || approved}>
      {approved ? (saving ? "Approving" : "Approved") : `Approve ${dow}'s plan`}
    </button>
  </>;

  return (
    <Page title="Tomorrow" actions={actions}>
      {fc.error && <ErrorBox error={fc.error} retry={fc.reload} />}
      {!f && !fc.error && <Skeleton h={340} />}
      {f && (
        <section className="hero tonight-hero"><Own a="demand" dark />
          <div>
            <div className="lab">{shortDate(next)} · expected orders</div>
            <div className="big"><Tween value={f.p50} /><span className="num rng">{Math.round(f.p10)}–{Math.round(f.p90)}</span></div>
            <div className="drv">
              <div><span>Rush</span><b>{clock(f.rush.start)}–{clock(f.rush.end)}</b></div>
              <div><span>Peak</span><b>{Math.round(f.rush.peak_per_15min)} per 15 min</b></div>
              {c0 && <div><span>Chashu</span><b><Tween value={have} /> portions</b></div>}
            </div>
          </div>
          <div>
            <div className="legend-inline"><span><i className="sw" style={{ background: "#b8e986" }} />Expected</span><span><i className="sw" style={{ background: "#8cc8ff" }} />Busy night</span>{c0 && <span><i className="sw" style={{ background: "#fbf0d6" }} />Pause</span>}</div>
            <PrepCurve curve={f.curve} busy={busy} have={c0 ? have : null} ppo={ppo} pause={pz} disabled={approved}
              onHave={(h) => c0 && setPrep(Math.max(0, Math.ceil((h - (c0.on_hand || 0)) / 10) * 10))} />
          </div>
        </section>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1.5fr 1fr", gap: 22, alignItems: "start" }}>
        <div className="card">
          <Own a="plan" />
          <div className="cardhead"><h3>Card</h3>{edited && !approved && <span className="ink2" style={{ fontSize: 14 }}>Edited from {cl.data!.card[0].prep}</span>}</div>
          {cl.loading && <Skeleton h={160} />}
          {!cl.loading && !cl.data && <div className="empty">No close for {fmtMonthDay(date)}</div>}
          {c0 && (
            <div className="prepline">
              <FoodIcon kind="chashu" size={44} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontWeight: 700, fontSize: 17 }}>{c0.item}</div>
                <div className="ink2 num" style={{ fontSize: 14 }}>Target {c0.target} · on hand {Math.round(c0.on_hand)} · recount at {c0.recount_at}</div>
                {c0.warnings?.map((w) => <div key={w} className="crit" style={{ fontSize: 13.5 }}>{w}</div>)}
                <input type="range" className="range light" aria-label="Prep" min={0} max={Math.max(200, Math.ceil((c0.target * 1.4) / 10) * 10)} step={10}
                  value={c0.prep} disabled={approved} onChange={(e) => setPrep(Number(e.target.value))} style={{ marginTop: 12 }} />
              </div>
              <div style={{ textAlign: "right" }}>
                <label htmlFor="prep-0" className="ink2" style={{ fontSize: 13 }}>Make</label>
                <NumberField id="prep-0" value={c0.prep} onChange={setPrep} step={10} disabled={approved}
                  style={{ width: 120, fontSize: 26, fontWeight: 700, textAlign: "right" }} />
              </div>
            </div>
          )}
          {c0 && pz && pzBusy && (
            <table className="tbl" style={{ marginTop: 12 }}>
              <thead><tr><th>App</th><th>Pause, expected</th><th>Pause, busy night</th><th className="r">Lead</th></tr></thead>
              <tbody>
                {APPS.map((a) => (
                  <tr key={a} data-app={a}>
                    <td style={{ fontWeight: 600 }}>{appName[a]}</td>
                    <td className="pz"><PauseCell t={pz[a]} /></td>
                    <td><PauseCell t={pzBusy[a]} /></td>
                    <td className="r ink2">{PAUSE_DELAY[a]} min</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
        <div className="card">
          <Own a="demand" />
          <div className="cardhead"><h3>Days like {dow}</h3></div>
          {!f && <Skeleton h={200} />}
          {f?.similar_days.map((s) => (
            <button className="clickrow" key={s.date} data-why onMouseEnter={() => why.prefetch({ kind: "day", date: s.date })} onClick={() => why.open({ kind: "day", date: s.date }, "tomorrow")}>
              <span><b style={{ fontWeight: 600 }}>{shortDate(s.date)}</b><span className="ink2" style={{ fontSize: 13.5, display: "block" }}>{s.why}</span></span>
              <b className="num">{s.orders}</b>
            </button>
          ))}
        </div>
      </div>
      <WhySlot anchor="tomorrow" />
    </Page>
  );
}

function PauseCell({ t }: { t: string | null }) {
  const [flash, setFlash] = useState(false);
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } setFlash(true); const x = setTimeout(() => setFlash(false), 260); return () => clearTimeout(x); }, [t]);
  return <span className={`num${flash ? " flash" : ""}`} style={{ fontWeight: t ? 700 : 400, color: t ? undefined : "var(--ink2)" }}>{t ? clock(t) : "Lasts the night"}</span>;
}

/** Forecast curve with a handle you drag to where chashu should run out; pause markers move with it. */
function PrepCurve({ curve, busy, have, ppo, pause, onHave, disabled, H = 300 }: {
  curve: Point[]; busy: Point[]; have: number | null; ppo: number; pause: Record<string, string | null> | null;
  onHave: (h: number) => void; disabled?: boolean; H?: number;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [drag, setDrag] = useState(false);
  const L = 34, R = 16, T = 40, B = 30;
  const pw = W - L - R, ph = H - T - B;
  const t0 = toMin(curve[0]?.time || "11:00"), t1 = toMin(curve[curve.length - 1]?.time || "22:15") + 15;
  const ymax = Math.max(4, ...busy.map((p) => p.orders), ...curve.map((p) => p.orders)) * 1.1;
  const x = (m: number) => L + (pw * (m - t0)) / (t1 - t0);
  const y = (v: number) => T + ph * (1 - v / ymax);
  const path = (pts: Point[]) => "M" + pts.map((p) => `${x(toMin(p.time) + 7.5).toFixed(1)},${y(p.orders).toFixed(1)}`).join("L");
  const ro = have !== null ? runOutMin(curve, have, ppo) : null;
  const hx = have === null ? null : ro === null ? x(t1) : x(ro);
  const toHave = (px: number) => {
    const m = t0 + ((px - L) / pw) * (t1 - t0);
    return m >= t1 - 1 ? portionsUntil(curve, t1, ppo) + 10 : portionsUntil(curve, Math.max(t0, m), ppo);
  };
  const ev = (e: React.PointerEvent) => { const r = (e.currentTarget as SVGElement).ownerSVGElement!.getBoundingClientRect(); return e.clientX - r.left; };
  // group apps that pause at the same time
  const marks = new Map<string, string[]>();
  if (pause) for (const [a, t] of Object.entries(pause)) if (t) marks.set(t, [...(marks.get(t) || []), appName[a]]);
  const area = `${path(curve)}L${x(toMin(curve[curve.length - 1].time) + 7.5)},${y(0)}L${x(toMin(curve[0].time) + 7.5)},${y(0)}Z`;
  return (
    <div ref={ref} className="chartwrap" style={{ height: H }}>
      <svg width={W} height={H} role="img" aria-label="Forecast and chashu run-out">
        {hx !== null && ro !== null && <rect x={hx} y={T} width={Math.max(0, x(t1) - hx)} height={ph} fill="#0b3d33" />}
        <path d={area} fill="#16614f" />
        <path d={path(busy)} fill="none" stroke="#8cc8ff" strokeWidth="2" strokeDasharray="1 5" strokeLinecap="round" />
        <path d={path(curve)} fill="none" stroke="#b8e986" strokeWidth="2.6" strokeLinejoin="round" />
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="#3d7a6c" />
        {[12, 14, 16, 18, 20, 22].map((h) => <text key={h} x={x(h * 60)} y={H - 8} fontSize="12" fill="#9fc2b8" textAnchor="middle">{h % 12 === 0 ? 12 : h % 12} {h >= 12 ? "pm" : "am"}</text>)}
        {[...marks].map(([t, apps], i) => (
          <g key={t} className="pmark" style={{ transform: `translateX(${x(toMin(t))}px)` }}>
            <line x1={0} x2={0} y1={T + 14 + i * 16} y2={y(0)} stroke="#fbf0d6" strokeWidth="1.5" strokeDasharray="3 3" />
            <text x={-6} y={T + 10 + i * 16} fontSize="12" fill="#fbf0d6" textAnchor="end" fontWeight="600">{apps.join(", ")} {clock(t)}</text>
          </g>
        ))}
        {hx !== null && (
          <g className={`handle${drag ? " on" : ""}`} style={{ cursor: disabled ? "default" : "ew-resize" }}
            role="slider" tabIndex={disabled ? -1 : 0} aria-label="Runs out at" aria-valuenow={Math.round(have!)} aria-valuetext={ro === null ? "Lasts the night" : clock(fromMin(ro))}
            onKeyDown={(e) => { if (disabled) return; if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); onHave(have! + (e.key === "ArrowRight" ? 10 : -10)); } }}
            onPointerDown={(e) => { if (disabled) return; (e.currentTarget as SVGGElement).setPointerCapture(e.pointerId); setDrag(true); }}
            onPointerMove={(e) => { if (drag) onHave(toHave(ev(e))); }}
            onPointerUp={() => setDrag(false)} data-testid="prep-handle">
            <line x1={hx} x2={hx} y1={T - 8} y2={y(0)} stroke="#b8e986" strokeWidth="2" />
            <rect x={hx - 16} y={y(0) - ph / 2 - 20} width="32" height="40" fill="transparent" />
            <rect x={hx - 5} y={y(0) - ph / 2 - 16} width="10" height="32" rx="5" fill="#b8e986" stroke="#0f4d40" strokeWidth="2" />
            <text x={hx + (hx > W - 160 ? -10 : 10)} y={T - 16} fontSize="13" fill="#b8e986" fontWeight="700" textAnchor={hx > W - 160 ? "end" : "start"}>
              {ro === null ? "Lasts the night" : `Runs out ${clock(fromMin(ro))}`}</text>
          </g>
        )}
      </svg>
    </div>
  );
}
