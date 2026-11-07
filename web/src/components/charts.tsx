import { useEffect, useLayoutEffect, useRef, useState, type ReactNode, type RefObject } from "react";
import type { IntradayBin, Point } from "../api/types";
import { fromMin, toMin } from "../lib/dates";
import { CH_COLOR, CHANNELS, appName, clock, money } from "./ui";

/** Measures an element's width so charts draw in real pixels (crisp text, exact hit targets). */
export function useWidth<T extends HTMLElement>(fallback = 800): [RefObject<T>, number] {
  const ref = useRef<T>(null);
  const [w, setW] = useState(fallback);
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    setW(el.clientWidth || fallback);
    const ro = new ResizeObserver(([e]) => setW(Math.max(200, Math.round(e.contentRect.width))));
    ro.observe(el);
    return () => ro.disconnect();
  }, [fallback]);
  return [ref, w];
}

const hourLabel = (m: number) => { const h = Math.floor(m / 60); return `${h % 12 === 0 ? 12 : h % 12} ${h >= 12 ? "pm" : "am"}`; };
const niceMax = (v: number) => { const p = Math.pow(10, Math.floor(Math.log10(Math.max(1, v)))); const n = v / p; return (n <= 1 ? 1 : n <= 2 ? 2 : n <= 2.5 ? 2.5 : n <= 5 ? 5 : 10) * p; };

export interface Pick { x: number; y: number }

function Tip({ x, w, children, dark }: { x: number; w: number; children: ReactNode; dark?: boolean }) {
  const left = Math.max(0, Math.min(x + 14, w - 200));
  return <div className={`ctip${dark ? " light" : ""}`} style={{ left, top: 6 }}>{children}</div>;
}

/* ---------------- Day curve: orders per 15 minutes, today vs usual ---------------- */

export function DayCurve({ today, usual, nowMin, rush, onPick, onHover, H = 300, dark = true, todayLabel = "Today", usualLabel = "Usual" }: {
  today: Point[]; usual: Point[]; nowMin?: number | null; rush?: { start: string; end: string } | null;
  onPick?: (p: { time: string; today: number | null; usual: number | null }, at: Pick) => void; H?: number; dark?: boolean;
  todayLabel?: string; usualLabel?: string; onHover?: (time: string) => void;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const L = 36, R = 16, T = 14, B = rush ? 52 : 30;
  const pw = W - L - R, ph = H - T - B;
  const times = Array.from(new Set([...usual, ...today].map((p) => p.time))).sort();
  if (!times.length) return <div ref={ref} style={{ height: H }} />;
  const t0 = Math.min(660, toMin(times[0])), t1 = Math.max(toMin(times[times.length - 1]) + 15, 1350);
  const ymax = niceMax(Math.max(10, ...today.map((p) => p.orders), ...usual.map((p) => p.orders)) * 1.08);
  const x = (m: number) => L + (pw * (m - t0)) / (t1 - t0);
  const y = (v: number) => T + ph * (1 - v / ymax);
  const mid = (p: Point) => toMin(p.time) + 7.5;
  const path = (pts: Point[]) => pts.length ? "M" + pts.map((p) => `${x(mid(p)).toFixed(1)},${y(p.orders).toFixed(1)}`).join("L") : "";
  const area = today.length ? `${path(today)}L${x(mid(today[today.length - 1])).toFixed(1)},${y(0)}L${x(mid(today[0])).toFixed(1)},${y(0)}Z` : "";
  const C = dark ? { area: "#16614f", line: "#b8e986", other: "#8cc8ff", axis: "#3d7a6c", text: "#9fc2b8", cross: "#cfe3dc" }
    : { area: "#dcebd0", line: "#0f4d40", other: "#8b938e", axis: "#d8ddd8", text: "#8b938e", cross: "#56605b" };
  const idxAt = (px: number) => { const m = t0 + ((px - L) / pw) * (t1 - t0); let best = 0, bd = 1e9; times.forEach((t, i) => { const d = Math.abs(toMin(t) + 7.5 - m); if (d < bd) { bd = d; best = i; } }); return best; };
  const at = (t: string, s: Point[]) => s.find((p) => p.time === t)?.orders ?? null;
  const hv = hover !== null ? times[hover] : null;
  const last = today[today.length - 1];
  useEffect(() => { if (hv && onHover) onHover(hv); }, [hv]); // eslint-disable-line
  return (
    <div ref={ref} className="chartwrap" style={{ height: H }} data-why>
      <svg width={W} height={H} role="img" aria-label="Orders per 15 minutes"
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(idxAt(e.clientX - r.left)); }}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => { if (hv && onPick) onPick({ time: hv, today: at(hv, today), usual: at(hv, usual) }, { x: e.clientX, y: e.clientY }); }}
        style={{ cursor: onPick ? "pointer" : undefined }}>
        {[0.5, 1].map((f) => <text key={f} x={L - 8} y={y(ymax * f) + 4} fontSize="12" fill={C.text} textAnchor="end">{Math.round(ymax * f)}</text>)}
        {area && <path d={area} fill={C.area} />}
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke={C.axis} />
        {usual.length > 0 && <path d={path(usual)} fill="none" stroke={C.other} strokeWidth="2" strokeDasharray="1 5" strokeLinecap="round" />}
        {today.length > 0 && <path className="draw" d={path(today)} fill="none" stroke={C.line} strokeWidth="2.6" strokeLinejoin="round" strokeLinecap="round" />}
        {nowMin != null && last && <>
          <line x1={x(nowMin)} x2={x(nowMin)} y1={T} y2={y(0)} stroke={C.line} strokeDasharray="2 4" />
          <circle className="pulse" cx={x(mid(last))} cy={y(last.orders)} r="5" fill={C.line} />
        </>}
        {[12, 14, 16, 18, 20, 22].map((h) => h * 60).filter((m) => m >= t0 && m <= t1).map((m) =>
          <text key={m} x={x(m)} y={y(0) + 18} fontSize="12" fill={C.text} textAnchor="middle">{hourLabel(m)}</text>)}
        {rush && (() => {
          const a = x(toMin(rush.start)), b = x(toMin(rush.end));
          return <>
            <rect x={a} y={y(0) + 30} width={Math.max(4, b - a)} height="6" rx="3" fill={C.line} />
            <text x={b + 8} y={y(0) + 37} fontSize="12.5" fill={C.line} fontWeight="600">Rush {clock(rush.start)}–{clock(rush.end)}</text>
          </>;
        })()}
        {hv && <line x1={x(toMin(hv) + 7.5)} x2={x(toMin(hv) + 7.5)} y1={T} y2={y(0)} stroke={C.cross} strokeWidth="1" />}
        {hv && at(hv, today) !== null && <circle cx={x(toMin(hv) + 7.5)} cy={y(at(hv, today)!)} r="4.5" fill={C.line} stroke={dark ? "#0f4d40" : "#fff"} strokeWidth="2" />}
      </svg>
      {hv && <Tip x={x(toMin(hv) + 7.5)} w={W} dark={dark}>
        <b>{clock(hv)}–{clock(fromMin(toMin(hv) + 15))}</b>
        {at(hv, today) !== null && <div><i className="sw" style={{ background: dark ? "#b8e986" : "#0f4d40" }} />{todayLabel} <span className="num">{Math.round(at(hv, today)!)}</span></div>}
        {at(hv, usual) !== null && <div><i className="sw" style={{ background: dark ? "#8cc8ff" : "#8b938e" }} />{usualLabel} <span className="num">{at(hv, usual)!.toFixed(1)}</span></div>}
      </Tip>}
    </div>
  );
}

/* ---------------- Intraday: stacked by channel ---------------- */

export function StackedBins({ bins, usual, hidden, onPick, onHover, H = 260, nowMin, selected }: {
  bins: IntradayBin[]; usual?: Point[]; hidden: Set<string>; onPick?: (b: IntradayBin, at: Pick) => void; onHover?: (b: IntradayBin) => void;
  H?: number; nowMin?: number | null; selected?: string | null;
}) {
  const [ref, W] = useWidth<HTMLDivElement>();
  const [hover, setHover] = useState<number | null>(null);
  const L = 36, R = 10, T = 12, B = 28;
  const pw = W - L - R, ph = H - T - B;
  const t0 = 660, t1 = Math.max(1350, ...bins.map((b) => toMin(b.time) + 15), ...(usual || []).map((p) => toMin(p.time) + 15));
  const shown = CHANNELS.filter((c) => !hidden.has(c));
  const tot = (b: IntradayBin) => shown.reduce((a, c) => a + (b.by_channel[c] || 0), 0);
  const ymax = niceMax(Math.max(10, ...bins.map(tot), ...(usual || []).map((p) => p.orders)) * 1.05);
  const x = (m: number) => L + (pw * (m - t0)) / (t1 - t0);
  const y = (v: number) => T + ph * (1 - v / ymax);
  const bw = Math.max(3, (pw / ((t1 - t0) / 15)) - 3);
  const idxAt = (px: number) => { const m = t0 + ((px - L) / pw) * (t1 - t0); const i = bins.findIndex((b) => m >= toMin(b.time) && m < toMin(b.time) + 15); return i < 0 ? null : i; };
  const hb = hover !== null ? bins[hover] : null;
  useEffect(() => { if (hb && onHover) onHover(hb); }, [hb?.time]); // eslint-disable-line
  const sb = selected ? bins.find((b) => b.time === selected) : null;
  return (
    <div ref={ref} className="chartwrap" style={{ height: H }} data-why>
      <svg width={W} height={H} role="img" aria-label="Orders per 15 minutes by channel"
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); setHover(idxAt(e.clientX - r.left)); }}
        onMouseLeave={() => setHover(null)}
        onClick={(e) => { if (hb && onPick) onPick(hb, { x: e.clientX, y: e.clientY }); }} style={{ cursor: onPick ? "pointer" : undefined }}>
        {[0.5, 1].map((f) => <g key={f}>
          <line x1={L} x2={L + pw} y1={y(ymax * f)} y2={y(ymax * f)} stroke="#efede6" />
          <text x={L - 8} y={y(ymax * f) + 4} fontSize="12" fill="#8b938e" textAnchor="end">{Math.round(ymax * f)}</text>
        </g>)}
        {bins.map((b) => {
          let acc = 0;
          const cx = x(toMin(b.time) + 7.5) - bw / 2;
          return <g key={b.time} className="grow">
            {shown.map((c) => {
              const v = b.by_channel[c] || 0; if (v <= 0) return null;
              const y0 = y(acc), y1 = y(acc + v); acc += v;
              return <rect key={c} x={cx} y={y1 + 1} width={bw} height={Math.max(0, y0 - y1 - 2)} rx="1.5" fill={CH_COLOR[c]} />;
            })}
          </g>;
        })}
        {usual && usual.length > 0 && <path d={"M" + usual.map((p) => `${x(toMin(p.time) + 7.5).toFixed(1)},${y(p.orders).toFixed(1)}`).join("L")}
          fill="none" stroke="#14201c" strokeWidth="1.6" strokeDasharray="1 4" strokeLinecap="round" />}
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="#d8ddd8" />
        {nowMin != null && <line x1={x(nowMin)} x2={x(nowMin)} y1={T} y2={y(0)} stroke="#0f4d40" strokeDasharray="2 4" />}
        {[12, 14, 16, 18, 20, 22].map((h) => <text key={h} x={x(h * 60)} y={H - 8} fontSize="12" fill="#8b938e" textAnchor="middle">{hourLabel(h * 60)}</text>)}
        {sb && <rect x={x(toMin(sb.time) + 7.5) - bw / 2 - 2} y={T} width={bw + 4} height={ph} fill="none" stroke="#14201c" strokeWidth="2" rx="2" />}
        {hb && hb !== sb && <rect x={x(toMin(hb.time) + 7.5) - bw / 2 - 2} y={T} width={bw + 4} height={ph} fill="none" stroke="#56605b" strokeWidth="1" rx="2" />}
      </svg>
      {hb && <Tip x={x(toMin(hb.time) + 7.5)} w={W}>
        <b>{clock(hb.time)} · {Math.round(tot(hb))} orders</b>
        {shown.map((c) => <div key={c}><i className="sw" style={{ background: CH_COLOR[c] }} />{appName[c]} <span className="num">{Math.round(hb.by_channel[c] || 0)}</span></div>)}
        {hb.net_sales ? <div className="muted">{money(hb.net_sales)}</div> : null}
      </Tip>}
    </div>
  );
}

export function ChannelLegend({ hidden, toggle }: { hidden: Set<string>; toggle: (c: string) => void }) {
  return (
    <div className="legend" role="group" aria-label="Channels">
      {CHANNELS.map((c) => (
        <button key={c} aria-pressed={!hidden.has(c)} className={hidden.has(c) ? "off" : ""} onClick={() => toggle(c)}>
          <i className="sw" style={{ background: hidden.has(c) ? "#d8ddd8" : CH_COLOR[c] }} />{appName[c]}
        </button>
      ))}
    </div>
  );
}

/* ---------------- Year chart with brush ---------------- */

export interface DayVal { date: string; value: number; orders?: number; closed?: boolean }

export function YearChart({ days, brush, onBrush, selected, picked, onPickDay, onHoverDay, onReset, fmt, H = 230 }: {
  days: DayVal[]; brush: [number, number]; onBrush: (a: number, b: number, final: boolean) => void; selected?: string; picked?: string | null;
  onPickDay: (d: DayVal, at: Pick) => void; onHoverDay?: (d: DayVal) => void; onReset: () => void; fmt: (v: number) => string; H?: number;
}) {
  const [ref, W] = useWidth<HTMLDivElement>(1100);
  const [hover, setHover] = useState<number | null>(null);
  const drag = useRef<{ mode: "new" | "move" | "l" | "r"; i0: number; a: number; b: number; x0: number; moved: boolean } | null>(null);
  const [dragging, setDragging] = useState(false);
  const L = 8, R = 8, T = 10, B = 30;
  const pw = W - L - R, ph = H - T - B;
  const n = days.length;
  const step = pw / Math.max(1, n);
  const ymax = niceMax(Math.max(1, ...days.map((d) => d.value)) * 1.04);
  const x = (i: number) => L + i * step;
  const y = (v: number) => T + ph * (1 - v / ymax);
  const idx = (px: number) => Math.max(0, Math.min(n - 1, Math.floor((px - L) / step)));
  const [a, b] = brush;
  const ax = x(a), bx = x(b + 1);
  const months = days.map((d, i) => ({ d, i })).filter(({ d }) => d.date.endsWith("-01"));
  const sel = selected ? days.findIndex((d) => d.date === selected) : -1;

  const down = (e: React.PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect(); const px = e.clientX - r.left + L;
    const i = idx(px);
    const mode = Math.abs(px - ax) < 8 ? "l" : Math.abs(px - bx) < 8 ? "r" : px > ax && px < bx ? "move" : "new";
    drag.current = { mode, i0: i, a, b, x0: e.clientX, moved: false };
    e.currentTarget.setPointerCapture(e.pointerId);
  };
  const move = (e: React.PointerEvent<SVGRectElement>) => {
    const r = e.currentTarget.getBoundingClientRect(); const px = e.clientX - r.left + L;
    const i = idx(px);
    const d = drag.current;
    if (!d) { setHover(i); const nearEdge = Math.abs(px - ax) < 8 || Math.abs(px - bx) < 8; e.currentTarget.style.cursor = nearEdge ? "ew-resize" : px > ax && px < bx ? "grab" : "crosshair"; return; }
    if (!d.moved && Math.abs(e.clientX - d.x0) < 4) return;
    d.moved = true; setDragging(true); setHover(null);
    let na = d.a, nb = d.b;
    if (d.mode === "new") { na = Math.min(d.i0, i); nb = Math.max(d.i0, i); }
    else if (d.mode === "move") { const len = d.b - d.a; na = Math.max(0, Math.min(n - 1 - len, d.a + (i - d.i0))); nb = na + len; }
    else if (d.mode === "l") { na = Math.min(i, d.b); }
    else { nb = Math.max(i, d.a); }
    onBrush(na, nb, false);
  };
  const up = (e: React.PointerEvent<SVGRectElement>) => {
    const d = drag.current; drag.current = null; setDragging(false);
    if (!d) return;
    if (!d.moved) { const r = e.currentTarget.getBoundingClientRect(); const i = idx(e.clientX - r.left + L); onPickDay(days[i], { x: e.clientX, y: e.clientY }); }
    else onBrush(brush[0], brush[1], true);
  };
  const hd = hover !== null ? days[hover] : null;
  useEffect(() => { if (hd && onHoverDay && !hd.closed) { const t = setTimeout(() => onHoverDay(hd), 120); return () => clearTimeout(t); } }, [hd?.date]); // eslint-disable-line
  const pk = picked ? days.findIndex((d) => d.date === picked) : -1;
  return (
    <div ref={ref} className="chartwrap" style={{ height: H }} data-why>
      <svg width={W} height={H} role="img" aria-label="Daily net sales for the year" className={dragging ? "dragging" : ""}>
        <rect x={ax} y={T - 4} width={Math.max(2, bx - ax)} height={ph + 4} fill="#e9f5dc" rx="3" />
        {days.map((d, i) => d.value > 0 && (
          <rect key={d.date} x={x(i) + (step > 3 ? 0.5 : 0)} y={y(d.value)} width={Math.max(1, step - (step > 3 ? 1 : 0.3))} height={y(0) - y(d.value)}
            fill={i === hover || i === pk ? "#14201c" : i >= a && i <= b ? "#0f4d40" : "#c3cbc5"} />
        ))}
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="#d8ddd8" />
        {months.map(({ d, i }) => <text key={d.date} x={x(i) + 2} y={H - 10} fontSize="12" fill="#8b938e">
          {new Date(`${d.date}T12:00:00`).toLocaleDateString("en-US", { month: "short" })}</text>)}
        {sel >= 0 && <path d={`M${x(sel) + step / 2},${y(0) + 3} l5,7 h-10 z`} fill="#14201c" />}
        {[["l", ax], ["r", bx]].map(([k, px]) => (
          <g key={k as string} className="handle">
            <rect x={(px as number) - 3} y={T + ph / 2 - 18} width="6" height="36" rx="3" fill="#14201c" />
          </g>
        ))}
        <rect x={L} y={0} width={pw} height={H - B + 8} fill="transparent" style={{ touchAction: "none" }}
          onPointerDown={down} onPointerMove={move} onPointerUp={up} onPointerLeave={() => !drag.current && setHover(null)}
          onDoubleClick={onReset} data-testid="year-overlay" />
      </svg>
      {hd && <Tip x={x(hover!) + step / 2} w={W}>
        <b>{new Date(`${hd.date}T12:00:00`).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" })}</b>
        {hd.closed || hd.value <= 0 ? <div>Closed</div> : <>
          <div>{fmt(hd.value)}</div>
          {hd.orders !== undefined && <div className="muted">{hd.orders} orders</div>}
        </>}
      </Tip>}
    </div>
  );
}

/* ---------------- Simple line/bar chart (Ask answers) ---------------- */

export function LineChart({ x, series, H = 220, kind = "line", fmt = (v: number) => v.toLocaleString() }: {
  x: string[]; series: { name: string; values: number[]; color?: string }[]; H?: number; kind?: "line" | "bar"; fmt?: (v: number) => string;
}) {
  const [ref, W] = useWidth<HTMLDivElement>(700);
  const [hover, setHover] = useState<number | null>(null);
  const L = 64, R = 12, T = 12, B = 26;
  const pw = W - L - R, ph = H - T - B;
  const ymax = niceMax(Math.max(1, ...series.flatMap((s) => s.values)) * 1.05);
  const n = x.length;
  const xs = (i: number) => L + (kind === "bar" ? (pw * (i + 0.5)) / n : (pw * i) / Math.max(1, n - 1));
  const y = (v: number) => T + ph * (1 - v / ymax);
  const colors = ["#0f4d40", "#3f86c9", "#e0703f"];
  const every = Math.max(1, Math.ceil(n / Math.max(2, Math.floor(pw / 70))));
  return (
    <div ref={ref} className="chartwrap" style={{ height: H }}>
      <svg width={W} height={H} role="img" aria-label={series.map((s) => s.name).join(", ")}
        onMouseMove={(e) => { const r = e.currentTarget.getBoundingClientRect(); const px = e.clientX - r.left; const i = kind === "bar" ? Math.floor(((px - L) / pw) * n) : Math.round(((px - L) / pw) * (n - 1)); setHover(i >= 0 && i < n ? i : null); }}
        onMouseLeave={() => setHover(null)}>
        {[0.5, 1].map((f) => <g key={f}>
          <line x1={L} x2={L + pw} y1={y(ymax * f)} y2={y(ymax * f)} stroke="#efede6" />
          <text x={L - 8} y={y(ymax * f) + 4} fontSize="12" fill="#8b938e" textAnchor="end">{fmt(ymax * f)}</text>
        </g>)}
        {series.map((s, si) => kind === "bar"
          ? s.values.map((v, i) => {
            const bw = Math.max(2, ((pw / n) * 0.72) / series.length);
            return <rect key={`${si}-${i}`} x={xs(i) - (pw / n) * 0.36 + si * bw} y={y(v)} width={bw - 1} height={Math.max(0, y(0) - y(v))} rx="2"
              fill={i === hover ? "#14201c" : s.color || colors[si]} />;
          })
          : <path key={si} d={"M" + s.values.map((v, i) => `${xs(i).toFixed(1)},${y(v).toFixed(1)}`).join("L")} fill="none"
            stroke={s.color || colors[si]} strokeWidth="2" strokeLinejoin="round" strokeLinecap="round" />)}
        <line x1={L} x2={L + pw} y1={y(0)} y2={y(0)} stroke="#d8ddd8" />
        {x.map((lbl, i) => i % every === 0 && <text key={i} x={xs(i)} y={H - 6} fontSize="12" fill="#8b938e" textAnchor="middle">{lbl}</text>)}
        {hover !== null && kind === "line" && <line x1={xs(hover)} x2={xs(hover)} y1={T} y2={y(0)} stroke="#56605b" />}
      </svg>
      {hover !== null && <Tip x={xs(hover)} w={W}>
        <b>{x[hover]}</b>
        {series.map((s, si) => <div key={si}><i className="sw" style={{ background: s.color || colors[si] }} />{s.name} <span className="num">{fmt(s.values[hover])}</span></div>)}
      </Tip>}
    </div>
  );
}

/** Horizontal bar used for channel / item breakdowns; width tweens. */
export function HBar({ value, max, color = "#0f4d40", track = "#ecebe5", h = 8 }: { value: number; max: number; color?: string; track?: string; h?: number }) {
  const [w, setW] = useState(0);
  useEffect(() => { setW(Math.max(0, Math.min(100, (value / Math.max(1e-9, max)) * 100))); }, [value, max]);
  return <div className="hbar" style={{ height: h, background: track }}><i style={{ width: `${w}%`, background: color }} /></div>;
}
