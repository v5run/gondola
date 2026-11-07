import { useEffect, useLayoutEffect, useRef, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";

export function Logo({ size = 34 }: { size?: number }) {
  return (
    <svg width={size} height={size} viewBox="0 0 26 26" aria-label="Gondola">
      <rect width="26" height="26" rx="5" fill="#0f4d40" />
      <rect x="6" y="7" width="14" height="2.6" fill="#b8e986" />
      <rect x="6" y="12" width="14" height="2.6" fill="#b8e986" />
      <rect x="6" y="17" width="14" height="2.6" fill="#b8e986" />
      <rect x="12" y="7" width="2" height="13" fill="#b8e986" />
    </svg>
  );
}

const P: Record<string, ReactNode> = {
  tonight: <path d="M15 4a8 8 0 1 0 5 13A7 7 0 0 1 15 4z" fill="currentColor" />,
  insights: <><rect x="3" y="12" width="3.4" height="7" rx="1" fill="currentColor" /><rect x="9.3" y="7" width="3.4" height="12" rx="1" fill="currentColor" /><rect x="15.6" y="3" width="3.4" height="16" rx="1" fill="currentColor" /></>,
  close: <><circle cx="11" cy="11" r="8" fill="none" stroke="currentColor" strokeWidth="2.2" /><path d="M7.5 11.2l2.4 2.4 4.6-5" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" /></>,
  tomorrow: <path d="M3 17 L8 11 L12 14 L19 6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />,
  service: <><rect x="3" y="5" width="16" height="12" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M7 11h3l1.5-3 2 6 1.5-3H17" fill="none" stroke="currentColor" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round" /></>,
  money: <><rect x="3" y="6" width="16" height="11" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><circle cx="11" cy="11.5" r="2.6" fill="currentColor" /></>,
  reports: <><rect x="4" y="3" width="14" height="16" rx="1.5" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M8 8h6M8 12h6M8 15.5h4" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /></>,
  ask: <path d="M4 5h14v9H9l-4 3.5V14H4z" fill="none" stroke="currentColor" strokeWidth="2" strokeLinejoin="round" />,
  alerts: <><rect x="6" y="2.5" width="10" height="17" rx="2.5" fill="none" stroke="currentColor" strokeWidth="2" /><circle cx="11" cy="16" r="1.2" fill="currentColor" /></>,
  past: <><circle cx="11" cy="11" r="8" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M11 6.5V11l3.2 2.2" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" /></>,
  present: <><path d="M3 11h3.2l2.2-5 3.4 10 2.4-5H19" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" /></>,
  future: <><path d="M3 16.5 8 11l3.4 3L18 6.5" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" /><path d="M13.5 6.2H18.4v4.9" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" /></>,
  review: <><rect x="4" y="3" width="14" height="16" rx="2" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M7.6 11.2l2.2 2.2 4.4-4.6" fill="none" stroke="currentColor" strokeWidth="2.1" strokeLinecap="round" strokeLinejoin="round" /></>,
  gear: <><path d="M3 6.5h16M3 15.5h16" stroke="currentColor" strokeWidth="2" strokeLinecap="round" /><circle cx="8" cy="6.5" r="2.6" fill="var(--bg)" stroke="currentColor" strokeWidth="2" /><circle cx="14" cy="15.5" r="2.6" fill="var(--bg)" stroke="currentColor" strokeWidth="2" /></>,
  left: <path d="M13.5 5 7.5 11l6 6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />,
  right: <path d="M8.5 5l6 6-6 6" fill="none" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />,
  x: <path d="M6 6l10 10M16 6 6 16" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" />,
  play: <path d="M7 4.5v13l11-6.5z" fill="currentColor" />,
  pause: <><rect x="6" y="4.5" width="3.6" height="13" rx="1" fill="currentColor" /><rect x="12.4" y="4.5" width="3.6" height="13" rx="1" fill="currentColor" /></>,
  search: <><circle cx="9.5" cy="9.5" r="5.5" fill="none" stroke="currentColor" strokeWidth="2" /><path d="M13.6 13.6 18 18" stroke="currentColor" strokeWidth="2.2" strokeLinecap="round" /></>,
};

export function Icon({ name, size = 22 }: { name: string; size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 22 22" aria-hidden="true">{P[name]}</svg>;
}

export function FoodIcon({ kind = "chashu", size = 34 }: { kind?: string; size?: number }) {
  const g: Record<string, ReactNode> = {
    chashu: <><rect x="4" y="11" width="26" height="14" rx="7" fill="#c98b6b" /><rect x="9" y="15" width="16" height="6" rx="3" fill="#f3d9c4" /></>,
    egg: <><ellipse cx="17" cy="18" rx="10" ry="12" fill="#fff6e5" /><circle cx="17" cy="20" r="6" fill="#f2b33d" /></>,
    bowl: <><path d="M4 15h26a13 11 0 0 1-26 0z" fill="#0f4d40" /><rect x="8" y="10" width="18" height="5" rx="2.5" fill="#c98b6b" /></>,
  };
  return <svg width={size} height={size} viewBox="0 0 34 34" aria-hidden="true">{g[kind]}</svg>;
}

export function Skeleton({ h = 140, w, r }: { h?: number; w?: number | string; r?: number }) {
  return <div className="skeleton" style={{ minHeight: h, width: w, borderRadius: r }} aria-busy="true" />;
}
/** A card-shaped placeholder: title bar and a few lines. */
export function SkeletonCard({ h = 220, lines = 3 }: { h?: number; lines?: number }) {
  return (
    <div className="card" aria-busy="true" style={{ minHeight: h, display: "flex", flexDirection: "column", gap: 12 }}>
      <div className="skeleton" style={{ minHeight: 18, width: "34%" }} />
      <div className="skeleton" style={{ minHeight: 42, width: "52%" }} />
      {Array.from({ length: lines }, (_, i) => <div key={i} className="skeleton" style={{ minHeight: 12, width: `${86 - i * 14}%` }} />)}
    </div>
  );
}

export function ErrorBox({ error, retry }: { error: string; retry?: () => void }) {
  return (
    <div className="error" role="alert">
      {error} {retry && <button className="link" onClick={retry} style={{ marginLeft: 8 }}>Try again</button>}
    </div>
  );
}

export function useLoad<T>(fn: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [n, setN] = useState(0);
  useEffect(() => {
    let on = true;
    setError(null); setLoading(true);
    fn().then((d) => { if (on) { setData(d); setLoading(false); } })
      .catch((e) => { if (on) { setError(String(e.message || e)); setLoading(false); } });
    return () => { on = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [...deps, n]);
  return { data, error, loading, reload: () => setN((x) => x + 1), setData };
}

/* ---------------- motion ---------------- */

export function useReducedMotion() {
  const [r, setR] = useState(() => typeof matchMedia !== "undefined" && matchMedia("(prefers-reduced-motion: reduce)").matches);
  useEffect(() => {
    const m = matchMedia("(prefers-reduced-motion: reduce)");
    const on = () => setR(m.matches);
    m.addEventListener("change", on);
    return () => m.removeEventListener("change", on);
  }, []);
  return r;
}

/** Animates a number towards `value` (ease-out, `ms` long). */
export function useTween(value: number, ms = 260) {
  const reduce = useReducedMotion();
  const [v, setV] = useState(value);
  const from = useRef(value);
  const cur = useRef(value);
  useEffect(() => {
    if (reduce || ms <= 0 || !Number.isFinite(value)) { cur.current = value; setV(value); return; }
    from.current = cur.current;
    const t0 = performance.now();
    let raf = 0;
    const f = (now: number) => {
      // The frame timestamp can precede the effect that scheduled it.
      const k = Math.max(0, Math.min(1, (now - t0) / ms));
      const e = 1 - Math.pow(1 - k, 3);
      cur.current = from.current + (value - from.current) * e;
      setV(cur.current);
      if (k < 1) raf = requestAnimationFrame(f);
    };
    raf = requestAnimationFrame(f);
    return () => cancelAnimationFrame(raf);
  }, [value, ms, reduce]);
  return v;
}

export function Tween({ value, fmt = (x) => Math.round(x).toLocaleString("en-US"), ms }: { value: number | null | undefined; fmt?: (v: number) => string; ms?: number }) {
  const ok = value !== null && value !== undefined && Number.isFinite(value);
  const v = useTween(ok ? (value as number) : 0, ms);
  return <span className="num">{ok ? fmt(v) : "–"}</span>;
}

/* ---------------- overlays ---------------- */

/** A popover anchored to a viewport point; flips to stay on screen. Closes on Escape or outside click. */
export function Popover({ x, y, onClose, children, width = 340 }: { x: number; y: number; onClose: () => void; children: ReactNode; width?: number }) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState({ left: x, top: y });
  useLayoutEffect(() => {
    const el = ref.current; if (!el) return;
    const h = el.offsetHeight;
    const left = Math.max(12, Math.min(x + 12, innerWidth - width - 12));
    const top = y + 12 + h > innerHeight - 12 ? Math.max(12, y - h - 12) : y + 12;
    setPos({ left, top });
  }, [x, y, width, children]);
  useEffect(() => {
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.contains(e.target as Node)) onClose(); };
    addEventListener("keydown", key);
    const t = setTimeout(() => addEventListener("mousedown", down), 0);
    return () => { removeEventListener("keydown", key); removeEventListener("mousedown", down); clearTimeout(t); };
  }, [onClose]);
  return createPortal(
    <div ref={ref} className="pop" role="dialog" style={{ left: pos.left, top: pos.top, width }}>{children}</div>, document.body);
}

export function Drawer({ open, onClose, children, label, width = 520 }: { open: boolean; onClose: () => void; children: ReactNode; label: string; width?: number }) {
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("keydown", key);
    return () => removeEventListener("keydown", key);
  }, [open, onClose]);
  if (!open) return null;
  return createPortal(
    <div className="drawer-scrim" onMouseDown={onClose}>
      <aside className="drawer" role="dialog" aria-label={label} style={{ width }} onMouseDown={(e) => e.stopPropagation()}>
        <button className="iconbtn drawer-x" onClick={onClose} aria-label="Close"><Icon name="x" size={18} /></button>
        {children}
      </aside>
    </div>, document.body);
}

export function Segmented<T extends string | number>({ value, options, onChange, label }: { value: T; options: [T, string][]; onChange: (v: T) => void; label: string }) {
  return (
    <div className="seg" role="radiogroup" aria-label={label}>
      {options.map(([v, l]) => (
        <button key={String(v)} role="radio" aria-checked={v === value} className={v === value ? "on" : ""} onClick={() => onChange(v)}>{l}</button>
      ))}
    </div>
  );
}

/** Number input that steps with arrow keys (Shift = ×5) and the scroll wheel. */
export function NumberField({ value, onChange, step = 1, min = 0, max = 99999, id, disabled, style, label }: {
  value: number; onChange: (v: number) => void; step?: number; min?: number; max?: number; id?: string; disabled?: boolean; style?: React.CSSProperties; label?: string;
}) {
  const ref = useRef<HTMLInputElement>(null);
  const clamp = (v: number) => Math.max(min, Math.min(max, v));
  useEffect(() => {
    const el = ref.current; if (!el) return;
    const wheel = (e: WheelEvent) => {
      if (disabled || document.activeElement !== el) return;
      e.preventDefault();
      onChange(clamp(value + (e.deltaY < 0 ? step : -step) * (e.shiftKey ? 5 : 1)));
    };
    el.addEventListener("wheel", wheel, { passive: false });
    return () => el.removeEventListener("wheel", wheel);
  });
  return (
    <input ref={ref} id={id} aria-label={label} className="input num" inputMode="numeric" disabled={disabled} style={style} value={value}
      onChange={(e) => onChange(clamp(Number(e.target.value.replace(/[^0-9]/g, "")) || 0))}
      onKeyDown={(e) => {
        if (e.key === "ArrowUp" || e.key === "ArrowDown") {
          e.preventDefault(); e.stopPropagation();
          onChange(clamp(value + (e.key === "ArrowUp" ? step : -step) * (e.shiftKey ? 5 : 1)));
        }
        if (e.key === "ArrowLeft" || e.key === "ArrowRight") e.stopPropagation();
      }} />
  );
}

/* ---------------- formatting ---------------- */

export const money = (v: number | null | undefined, d = 0) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${v < 0 ? "−" : ""}$${Math.abs(v).toLocaleString("en-US", { minimumFractionDigits: d, maximumFractionDigits: d })}`;
export const pct = (v: number | null | undefined, d = 0, sign = true) =>
  v === null || v === undefined || Number.isNaN(v) ? "–" : `${sign && v > 0 ? "+" : v < 0 ? "−" : ""}${Math.abs(v * 100).toFixed(d)}%`;
export const compactMoney = (v: number) => (Math.abs(v) >= 1000 ? `$${(v / 1000).toFixed(v >= 10000 ? 0 : 1)}k` : `$${Math.round(v)}`);
export const appName: Record<string, string> = { doordash: "DoorDash", ubereats: "Uber Eats", grubhub: "Grubhub", in_store: "Dine-in", dine_in: "Dine-in", pickup: "Pickup" };
/** Channel colors, validated as a categorical set (fixed order, never cycled). Pickup is the fifth hue for the queue. */
export const CH_COLOR: Record<string, string> = { in_store: "#1f7a62", dine_in: "#1f7a62", doordash: "#e0703f", ubereats: "#3f86c9", grubhub: "#c99a14", pickup: "#8a64b4" };
export const CHANNELS = ["in_store", "doordash", "ubereats", "grubhub"] as const;

/** "21:15" -> "9:15 pm" */
export function clock(t?: string | null) {
  if (!t) return "–";
  if (/[ap]m$/i.test(t.trim())) return t.trim().toLowerCase();
  const [h, m] = t.split(":").map(Number);
  const suf = h >= 12 ? "pm" : "am";
  const h12 = h % 12 === 0 ? 12 : h % 12;
  return `${h12}:${String(m).padStart(2, "0")} ${suf}`;
}

export function longDate(iso: string) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("en-US", { weekday: "long", month: "short", day: "numeric" });
}
export function shortDate(iso: string) {
  const d = new Date(`${iso}T12:00:00`);
  return d.toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
}

/** A compact 0–1 bar (confidence, budget use). */
export function HBarInline({ v, color }: { v: number; color?: string }) {
  const w = Math.max(0, Math.min(1, v)) * 100;
  return <span className="hbi" aria-hidden="true"><i style={{ width: `${w}%`, background: color || (v < 0.3 ? "var(--crit)" : v < 0.6 ? "var(--warn)" : "var(--green)") }} /></span>;
}
