import { useMemo, useState } from "react";
import type { FutureBin, FutureDriver, LimitedItem } from "../api/tri";
import { Evidence } from "./review";
import { toMin, fromMin } from "../lib/dates";
import { useWidth } from "./charts";
import { CH_COLOR, appName, clock, pct } from "./ui";

/** Rest of today: P10–P90 band, P50 line and the actual orders per 15 minutes, for all channels or one. Drivers with a time are flagged on the curve. */
export function NowcastChart({ bins, channel, nowMin, drivers, H = 270 }: { bins: FutureBin[]; channel: string; nowMin: number | null; drivers: FutureDriver[]; H?: number }) {
  const [ref, W] = useWidth<HTMLDivElement>(800);
  const [hover, setHover] = useState<number | null>(null);
  const pts = useMemo(() => {
    const by = new Map<string, { time: string; p10: number; p50: number; p90: number; actual: number | null }>();
    for (const b of bins) {
      if (channel !== "all" && b.channel !== channel) continue;
      const x = by.get(b.time) || { time: b.time, p10: 0, p50: 0, p90: 0, actual: null as number | null };
      x.p10 += b.p10; x.p50 += b.p50; x.p90 += b.p90;
      if (b.actual !== null && b.actual !== undefined) x.actual = (x.actual ?? 0) + b.actual;
      by.set(b.time, x);
    }
    return [...by.values()].sort((a, b) => a.time.localeCompare(b.time));
  }, [bins, channel]);
  if (!pts.length) return <div ref={ref} className="chartwrap" style={{ height: H }} />;
  const L = 34, R = 14, T = 44, B = 28;
  const pw = W - L - R, ph = H - T - B;
  const t0 = toMin(pts[0].time), t1 = toMin(pts[pts.length - 1].time) + 15;
  const ymax = Math.max(4, ...pts.map((p) => Math.max(p.p90, p.actual ?? 0))) * 1.08;
  const x = (m: number) => L + (pw * (m - t0)) / (t1 - t0);
  const y = (v: number) => T + ph * (1 - v / ymax);
  const mid = (p: { time: string }) => x(toMin(p.time) + 7.5);
  const band = `M${pts.map((p) => `${mid(p).toFixed(1)},${y(p.p90).toFixed(1)}`).join("L")}L${[...pts].reverse().map((p) => `${mid(p).toFixed(1)},${y(p.p10).toFixed(1)}`).join("L")}Z`;
  const line = `M${pts.map((p) => `${mid(p).toFixed(1)},${y(p.p50).toFixed(1)}`).join("L")}`;
  const bw = Math.max(2, (pw / pts.length) * 0.62);
  const flags = drivers.filter((d) => d.time && toMin(d.time) >= t0 && toMin(d.time) <= t1);
  const hi = hover !== null ? pts[hover] : null;
  return (
    <div ref={ref} className="chartwrap" style={{ height: H }}>
      <svg width={W} height={H} role="img" aria-label="Expected and actual orders per 15 minutes"
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const m = t0 + ((e.clientX - r.left - L) / pw) * (t1 - t0); const i = Math.floor((m - t0) / 15); setHover(i >= 0 && i < pts.length ? i : null); }}
        onMouseLeave={() => setHover(null)}>
        {[0.5, 1].map((f) => <text key={f} x={L - 8} y={y(ymax * f / 1.08) + 4} fontSize="12" fill="#9fc2b8" textAnchor="end">{Math.round(ymax * f / 1.08)}</text>)}
        {nowMin !== null && nowMin > t0 && <rect x={L} y={T} width={Math.max(0, Math.min(pw, x(nowMin) - L))} height={ph} fill="#0b3d33" />}
        <path d={band} fill="#1b5d4e" />
        {pts.map((p, i) => p.actual !== null && (
          <rect key={p.time} x={mid(p) - bw / 2} y={y(p.actual)} width={bw} height={Math.max(0, y(0) - y(p.actual))} rx="2" fill={i === hover ? "#fbf0d6" : channel === "all" ? "#8cc8ff" : CH_COLOR[channel] || "#8cc8ff"} />
        ))}
        <path d={line} fill="none" stroke="#b8e986" strokeWidth="2.4" strokeLinejoin="round" />
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="#3d7a6c" />
        {nowMin !== null && nowMin > t0 && nowMin < t1 && <g><line x1={x(nowMin)} x2={x(nowMin)} y1={T} y2={y(0)} stroke="#fff" strokeWidth="1.5" /></g>}
        {flags.map((d, i) => {
          const fx = x(toMin(d.time!));
          const right = fx > W - 200;
          return <g key={d.label} className="flag">
            <line x1={fx} x2={fx} y1={T - 26 + i * 15 + 4} y2={y(0)} stroke="#fbf0d6" strokeWidth="1.2" strokeDasharray="3 3" />
            <text x={right ? fx - 6 : fx + 6} y={T - 26 + i * 15 + 10} fontSize="12" fill="#fbf0d6" fontWeight="600" textAnchor={right ? "end" : "start"}>{d.label}</text>
          </g>;
        })}
        {[12, 14, 16, 18, 20, 22].map((h) => h * 60 >= t0 && h * 60 <= t1 && <text key={h} x={x(h * 60)} y={H - 8} fontSize="12" fill="#9fc2b8" textAnchor="middle">{h % 12 === 0 ? 12 : h % 12} {h >= 12 ? "pm" : "am"}</text>)}
        {hi && <line x1={mid(hi)} x2={mid(hi)} y1={T} y2={y(0)} stroke="#fbf0d6" strokeWidth="1" />}
      </svg>
      {hi && <div className="ctip light" style={{ left: Math.min(W - 190, Math.max(0, mid(hi) + 12)), top: T }}>
        <b>{clock(hi.time)}–{clock(fromMin(toMin(hi.time) + 15))}</b>
        <div>Expected <span className="num">{hi.p50.toFixed(0)}</span> <span className="ink2">({hi.p10.toFixed(0)}–{hi.p90.toFixed(0)})</span></div>
        {hi.actual !== null && <div>Actual <span className="num">{hi.actual}</span></div>}
      </div>}
    </div>
  );
}

/** Reasons tonight may differ, with effect bars; click a reason for its why. */
export function DriverList({ drivers, testid = "drivers" }: { drivers: FutureDriver[]; testid?: string }) {
  const [open, setOpen] = useState<number | null>(null);
  const max = Math.max(0.05, ...drivers.map((d) => Math.abs(d.effect_pct)));
  if (!drivers.length) return <div className="ink2">No unusual drivers</div>;
  return (
    <div className="olrows" role="list" data-testid={testid}>
      {drivers.map((d, i) => (
        <div key={`${d.label}-${i}`} role="listitem">
          <button className="olrow" aria-expanded={open === i} onClick={() => setOpen((x) => (x === i ? null : i))} data-kind={d.kind}>
            <span className="lab">{d.label}{d.estimate ? <span className="est">estimate</span> : null}</span>
            <span className="tm">{[d.time ? clock(d.time) : d.window, d.channel_note].filter(Boolean).join(" · ")}</span>
            <span className="drv-bar">{d.effect_pct !== 0 && <i className={d.effect_pct > 0 ? "pos" : "neg"} style={{ width: `${(Math.abs(d.effect_pct) / max) * 50}%` }} />}</span>
            <b className={d.effect_pct < 0 ? "crit" : undefined}>{d.effect_pct === 0 ? "–" : pct(d.effect_pct, 0)}</b>
          </button>
          {open === i && <div className="olwhy" data-testid="driver-why">{d.why}<Evidence ev={d.evidence} max={6} /></div>}
        </div>
      ))}
    </div>
  );
}

/** One limited item: what's left, and a clock from now to close with the runout and each app's pause. */
export function ItemClock({ it, nowMin, closeMin = 22 * 60 }: { it: LimitedItem; nowMin: number | null; closeMin?: number }) {
  const start = nowMin ?? 11 * 60;
  const span = Math.max(30, closeMin - start);
  const x = (t: string) => Math.max(0, Math.min(100, ((toMin(t) - start) / span) * 100));
  const ro = it.projected_runout;
  const out = it.believed_left <= 0;
  const pauses = Object.entries(it.pause_at || {}).filter(([, t]) => t) as [string, string][];
  return (
    <div className={`iclock${ro ? " runs" : ""}`} data-item={it.key}>
      <div className="ic-top"><b>{it.name}</b><span className={ro ? "crit" : "ink2"}>{out ? "Sold out" : ro ? `Runs out ${clock(ro)}` : "Lasts the night"}</span></div>
      <div className="ic-left num">{Math.round(it.believed_left)}<small>{it.unit ? `${it.unit} left` : "left"}</small></div>
      <div className="ic-line" aria-hidden="true">
        {ro && <i className="ic-gone" style={{ left: `${x(ro)}%` }} />}
        {pauses.map(([a, t]) => <span key={a} className="ic-p" style={{ left: `${x(t)}%`, background: CH_COLOR[a] }} />)}
        {ro && <span className="ic-ro" style={{ left: `${x(ro)}%` }} />}
      </div>
      <div className="ic-axis ink2"><span>{nowMin !== null ? "Now" : clock(fromMin(start))}</span><span>{clock(fromMin(closeMin))}</span></div>
      <div className="ic-pz">
        {pauses.length ? pauses.map(([a, t]) => <span key={a}><i className="sw" style={{ background: CH_COLOR[a] }} />{appName[a]} {clock(t)}</span>)
          : <span className="ink2">No pauses needed</span>}
        {it.recount_at !== null && it.recount_at !== undefined && <span className="ink2">Recount at {it.recount_at}</span>}
      </div>
    </div>
  );
}
