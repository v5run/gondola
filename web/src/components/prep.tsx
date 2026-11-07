import { useEffect, useRef, useState } from "react";
import type { Point } from "../api/types";
import { useWidth } from "./charts";
import { appName, clock } from "./ui";
import { fromMin, toMin } from "../lib/dates";
import { portionsUntil, runOutMin } from "../lib/plan";

export function PauseCell({ t }: { t: string | null }) {
  const [flash, setFlash] = useState(false);
  const first = useRef(true);
  useEffect(() => { if (first.current) { first.current = false; return; } setFlash(true); const x = setTimeout(() => setFlash(false), 260); return () => clearTimeout(x); }, [t]);
  return <span className={`num${flash ? " flash" : ""}`} style={{ fontWeight: t ? 700 : 400, color: t ? undefined : "var(--ink2)" }}>{t ? clock(t) : "Lasts the night"}</span>;
}

/** Forecast curve with a handle you drag to where chashu should run out; pause markers move with it. */
export function PrepCurve({ curve, busy, have, ppo, pause, onHave, disabled, H = 300, item = "it", step = 10 }: {
  curve: Point[]; busy: Point[]; have: number | null; ppo: number; pause: Record<string, string | null> | null;
  onHave: (h: number) => void; disabled?: boolean; H?: number; item?: string; step?: number;
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
      <svg width={W} height={H} role="img" aria-label={`Forecast and ${item} run-out`}>
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
            onKeyDown={(e) => { if (disabled) return; if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); onHave(have! + (e.key === "ArrowRight" ? step : -step)); } }}
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
