import { useEffect, useLayoutEffect, useMemo, useRef, useState, type KeyboardEvent as KE } from "react";
import { FACTOR_KEYS, factorMin, factorNote, levelKey, tri, type Action, type ChannelState, type Compare, type CompareSide, type PresentSettings, type PresentState, type QueueRow, type Simulation, type Station } from "../api/tri";
import { toMin, fromMin } from "../lib/dates";
import { LEVEL_NAME, actionText, actor } from "../live";
import { Info } from "./Info";
import { CH_COLOR, Drawer, ErrorBox, Popover, Skeleton, appName, clock } from "./ui";
import { Own } from "../agents";

export const DEFAULT_SETTINGS: PresentSettings = {
  ladder: { promote_above: 20, quote_below: 0, pause_below: -10, busy_below: -25, hysteresis_min: 2 },
  weights: { courier: 1, distance: 0.6, hold: 0.8, weather: 0.5, batch: 0.7, fairness: 1, in_store: 1 }, max_wait_min: 35,
};
const LO = -40, HI = 40;
/** Each rung and the guarded action its what-if simulates (the Rush agent's allowed actions). */
export const LEVELS = [
  { key: "busy", name: "Busy mode", short: "Busy", act: { action: "busy", channel: "grubhub" } },
  { key: "pause_items", name: "Pause slow items", short: "Pause items", act: { action: "pause_item", channel: "grubhub", item: "Karaage" } },
  { key: "quote", name: "Quote longer", short: "Quote", act: { action: "quote", channel: "delivery", value: 8 } },
  { key: "normal", name: "Normal", short: "Normal", act: { action: "resume", channel: "delivery" } },
  { key: "promote", name: "Promote", short: "Promote", act: { action: "offer", item: "Karaage", value: 100 } },
] as const;
export const FACTOR_NAME: Record<string, string> = { courier: "Courier", distance: "Drive distance", hold: "Hold tolerance", weather: "Weather", batch: "Station batch", fairness: "Fairness cap", in_store: "Guest here" };
const PARAM_NAME: Record<string, string> = {
  courier_far_cap_min: "Most slack a far courier adds", courier_arriving_min: "Courier counts as arriving within", rain_buffer_min: "Rain buffer", snow_buffer_min: "Snow buffer",
  cold_hold_factor: "Hold tolerance when cold", cold_temp_c: "Cold below", batch_window_min: "Batch items due within", urgent_slack_min: "Urgent below slack", reshuffle_margin_min: "Reorder only for a gain over",
};
const STATUS_NAME: Record<string, string> = { queued: "Queued", cooking: "Cooking", packing: "Packing", ready: "Ready" };

/** Ladder zones from the settings, low to high. */
function zones(s: PresentSettings) {
  const L = s.ladder;
  const cuts = [LO, L.busy_below, L.pause_below, L.quote_below, L.promote_above, HI];
  return LEVELS.map((l, i) => ({ ...l, from: cuts[i], to: cuts[i + 1] }));
}
export const zoneOf = (s: PresentSettings, h: number) => zones(s).find((z) => h >= z.from && h < z.to)?.key ?? (h >= HI ? "promote" : "busy");

const fmtPct = (v: number) => { const r = Math.round(v); return `${r > 0 ? "+" : r < 0 ? "−" : ""}${Math.abs(r)}%`; };

/* ================= the admission ladder ================= */

export function LadderHero({ st, settings, date, onSettings }: { st: PresentState; settings: PresentSettings; date: string; onSettings?: () => void }) {
  const zs = zones(settings);
  const h = st.headroom_pct;
  // the ladder's own level (it holds a step for the hysteresis time), not just the zone the headroom sits in
  const cur = st.ladder ? levelKey(st.ladder.level) : zoneOf(settings, h);
  // five equal zones; the marker sits proportionally inside its zone
  const W = 100 / zs.length;
  const x = (v: number) => {
    const c = Math.max(LO, Math.min(HI, v));
    const i = Math.max(0, zs.findIndex((z) => c >= z.from && c < z.to));
    const z = zs[c >= HI ? zs.length - 1 : i];
    return (zs.indexOf(z) + Math.max(0, Math.min(1, (c - z.from) / Math.max(1e-6, z.to - z.from)))) * W;
  };
  const [sim, setSim] = useState<{ x: number; y: number; level: string; res?: Simulation; err?: string } | null>(null);
  const trySim = async (e: React.MouseEvent, z: (typeof zs)[number]) => {
    const r = (e.currentTarget as HTMLElement).getBoundingClientRect();
    setSim({ x: r.left, y: r.bottom, level: z.name });
    try { const res = await tri.present.simulate(date, { ...z.act }); setSim((s) => (s && s.level === z.name ? { ...s, res } : s)); }
    catch (err) { setSim((s) => (s ? { ...s, err: String((err as Error).message) } : s)); }
  };
  return (
    <section className="hero ladder" aria-label="Admission ladder" data-testid="ladder"><Own a="controller" dark /><Info k="app_state" dark />
      <div className="ladder-head">
        <div className="lab">Headroom<Info k="headroom" dark inline /></div>
        <div className={`big num${h < 0 ? " neg" : ""}`} data-testid="headroom">{fmtPct(h)}</div>
        <div className="ladder-level"><b data-testid="ladder-level">{LEVEL_NAME[cur] || st.ladder.name}</b>{st.ladder.since ? ` since ${clock(st.ladder.since)}` : ""}<Info k="ladder" dark inline /></div>
        {st.weather && <div className="wx">{st.weather.rain ? "Rain" : "Dry"}{st.weather.temp_c !== null ? ` · ${Math.round(st.weather.temp_c)}°C` : ""}</div>}
      </div>
      <div className="ladder-gauge">
        <div className="gauge" role="img" aria-label={`Headroom ${fmtPct(h)}, ${LEVEL_NAME[cur]}`}>
          {zs.map((z, i) => <i key={z.key} className={z.key === cur ? "on" : ""} style={{ left: `${i * W}%`, width: `calc(${W}% - 3px)` }} />)}
          <span className="gauge-mark" style={{ left: `${x(h)}%` }} />
        </div>
        <div className="gauge-cuts">
          {zs.slice(1).map((z, i) => <span key={z.key} className="num" style={{ left: `calc(${(i + 1) * W}% - 1.5px)` }}>{fmtPct(z.from)}</span>)}
        </div>
        <div className="gauge-zones">
          {zs.map((z, i) => (
            <button key={z.key} className={z.key === cur ? "on" : ""} style={{ left: `${i * W}%`, width: `calc(${W}% - 3px)` }}
              onClick={(e) => trySim(e, z)} aria-label={`What if: ${z.name}`} data-level={z.key}>{z.short}</button>
          ))}
        </div>
        {onSettings && <button className="link ladder-set" onClick={onSettings}>Thresholds and weights</button>}
      </div>
      <div className="apps" data-testid="apps">
        {["doordash", "ubereats", "grubhub", "pickup", "dine_in"].map((c) => <AppLine key={c} ch={c} s={st.channels[c] || (c === "dine_in" ? st.channels.in_store : undefined)} />)}
      </div>
      {sim && <Popover x={sim.x} y={sim.y} onClose={() => setSim(null)} width={320}>
        <div className="pop-q">What if: {sim.level}</div>
        {sim.err ? <div className="crit">{sim.err}</div> : !sim.res ? <div className="pop-load"><span className="skeleton" /><span className="skeleton" /></div> : <>
          <dl>
            <dt>Headroom</dt><dd>{fmtPct(sim.res.headroom_pct_before)} → {fmtPct(sim.res.headroom_pct_after)}</dd>
            <dt>Late orders, next 30 min</dt><dd>{sim.res.late_orders_before} → {sim.res.late_orders_after}</dd>
            {sim.res.late_minutes_before !== undefined && <><dt>Late minutes</dt><dd>{Math.round(sim.res.late_minutes_before)} → {Math.round(sim.res.late_minutes_after ?? 0)}</dd></>}
            {!!sim.res.lost_orders && <><dt>Orders turned away</dt><dd>{sim.res.lost_orders}</dd></>}
          </dl>
          {(Array.isArray(sim.res.notes) ? sim.res.notes : [sim.res.notes]).filter(Boolean).slice(-1).map((n) => <div key={n} className="ink2" style={{ fontSize: 13.5 }}>{n}</div>)}
        </>}
      </Popover>}
    </section>
  );
}

function AppLine({ ch, s }: { ch: string; s?: ChannelState }) {
  const st = s?.state || "open";
  const text = st === "quoted" ? `Quoting +${s?.quoted_extra_min ?? "?"} min` : st === "paused_items" ? `Paused ${(s?.paused_items || []).join(", ") || "items"}` : st === "busy" ? "Busy" : "Open";
  return (
    <div className={`appline ${st}`} data-ch={ch} data-state={st}>
      <i className="sw" style={{ background: CH_COLOR[ch] }} /><span>{appName[ch]}</span><b>{text}</b>
    </div>
  );
}

/* ================= the queue ================= */

/** FLIP: rows slide to their new rank instead of jumping. */
function useFlip(keys: string[]) {
  const els = useRef(new Map<string, HTMLElement>());
  const prev = useRef(new Map<string, number>());
  useLayoutEffect(() => {
    const next = new Map<string, number>();
    els.current.forEach((el, k) => { if (el.isConnected) next.set(k, el.offsetTop); });
    if (!matchMedia("(prefers-reduced-motion: reduce)").matches) {
      next.forEach((top, k) => {
        const was = prev.current.get(k);
        const el = els.current.get(k);
        if (was === undefined || !el || was === top) return;
        el.style.transition = "none";
        el.style.transform = `translateY(${was - top}px)`;
        requestAnimationFrame(() => { el.style.transition = "transform .45s cubic-bezier(.2,.8,.2,1)"; el.style.transform = ""; });
      });
    }
    prev.current = next;
  }, [keys.join("|")]); // eslint-disable-line
  return (k: string) => (el: HTMLElement | null) => { if (el) els.current.set(k, el); else els.current.delete(k); };
}

export function QueueBoard({ rows, elapsed, sel, setSel, hover, setHover, fresh, closed }: {
  rows: QueueRow[]; elapsed: number; sel: string | null; setSel: (id: string | null) => void; hover: string | null; setHover: (id: string | null) => void;
  fresh: Set<string>; closed: boolean;
}) {
  const ref = useFlip(rows.map((r) => r.order_id));
  const list = useRef<HTMLDivElement>(null);
  const move = (e: KE, i: number) => {
    if (e.key !== "ArrowDown" && e.key !== "ArrowUp") return;
    e.preventDefault();
    const btns = list.current?.querySelectorAll<HTMLElement>(".qrow");
    btns?.[Math.max(0, Math.min((btns?.length || 1) - 1, i + (e.key === "ArrowDown" ? 1 : -1)))]?.focus();
  };
  const smax = 15;
  return (
    <div className="queue" ref={list} role="list" aria-label="Order queue" data-testid="queue">
      <div className="qhead" aria-hidden="true"><span>#</span><span>Order</span><span>Channel</span><span>Due</span><span>Slack<Info k="slack" inline /></span><span>Courier</span><span>Status</span></div>
      {rows.length === 0 && <div className="empty">{closed ? "Closed: the queue is empty" : "No open orders"}</div>}
      {rows.map((r, i) => {
        const slack = r.slack_min === null || r.slack_min === undefined ? null : r.slack_min - (r.status === "queued" ? elapsed : 0);
        const w = slack === null ? 0 : Math.min(1, Math.abs(slack) / smax) * 100;
        const open = sel === r.order_id;
        return (
          <div key={r.order_id} ref={ref(r.order_id)} role="listitem" className={`qitem${open ? " open" : ""}${hover === r.order_id ? " hov" : ""}${fresh.has(r.order_id) ? " fresh" : ""}`} data-order={r.order_id} data-rank={r.rank}>
            <div className="qrow" role="button" tabIndex={0} aria-expanded={open} onClick={() => setSel(open ? null : r.order_id)}
              onKeyDown={(e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); setSel(open ? null : r.order_id); } else move(e, i); }}
              onMouseEnter={() => setHover(r.order_id)} onMouseLeave={() => setHover(null)} data-testid="qrow">
              <span className="num rank">{r.rank}</span>
              <span className="qorder"><b>{r.order_id}</b><span>{r.items.join(", ")}</span></span>
              <span className="qch"><i className="sw" style={{ background: CH_COLOR[r.channel] || "#8b938e" }} />{appName[r.channel] || r.channel}</span>
              <span className="num">{clock(r.due)}</span>
              {slack === null ? <span className="slack"><span /><b className="ink2">–</b></span> : <span className="slack">
                <span className="slackbar"><i className={slack < 0 ? "neg" : "pos"} style={{ width: `${w / 2}%` }} /></span>
                <b className={`num${slack < 0 ? " crit" : ""}`}>{slack < 0 ? "−" : ""}{Math.abs(slack).toFixed(Math.abs(slack) < 10 ? 1 : 0)}</b>
              </span>}
              <span className="qcourier num">{courierText(r)}</span>
              <span className={`qst ${r.status}`}><i className="dot" />{STATUS_NAME[r.status] || r.status}</span>
            </div>
            {open && <Factors r={r} slack={slack} />}
          </div>
        );
      })}
    </div>
  );
}

function courierText(r: QueueRow) {
  if (r.fulfillment === "dine_in" || r.channel === "dine_in") return "Guest here";
  if (r.fulfillment === "pickup" || r.channel === "pickup") return r.promise ? `Pickup ${clock(r.promise)}` : "Pickup";
  if (r.courier_arrived) return "Courier here";
  if (!r.courier_eta) return "Not assigned";
  return `${clock(r.courier_eta)}${r.courier_distance_km !== null && r.courier_distance_km !== undefined ? ` · ${r.courier_distance_km.toFixed(1)} km` : ""}`;
}

function Factors({ r, slack }: { r: QueueRow; slack: number | null }) {
  const vals = FACTOR_KEYS.map((k) => ({ k, v: factorMin(r.factors[k]), note: factorNote(r.factors[k]) }));
  const max = Math.max(3, ...vals.map((x) => Math.abs(x.v)));
  return (
    <div className="factors enter" data-testid="factors">
      <div className="freason">{r.reason}</div>
      <div className="fgrid">
        <div className="fbars" aria-label="Factor breakdown">
          {vals.map(({ k, v, note }) => (
            <div key={k} className="drv-row frow" data-factor={k} title={note || undefined}>
              <span className="drv-k">{FACTOR_NAME[k]}<Info k={`factor_${k}`} inline /></span>
              <span className="drv-bar">{v !== 0 && <i className={v > 0 ? "pos" : "neg"} style={{ width: `${(Math.abs(v) / max) * 50}%` }} />}</span>
              <b className={`num${v < 0 ? " crit" : ""}`}>{v === 0 ? "–" : `${v > 0 ? "+" : "−"}${Math.abs(v).toFixed(1)}`}</b>
            </div>
          ))}
        </div>
        <dl className="facts ffacts">
          <dt>Latest start</dt><dd>{clock(r.latest_start)}</dd>
          <dt>Slack</dt><dd className={slack !== null && slack < 0 ? "crit" : undefined}>{slack === null ? "–" : `${slack.toFixed(1)} min`}</dd>
          {r.planned_ready && <><dt>Planned ready</dt><dd>{clock(r.planned_ready)}</dd></>}
          <dt>Promise</dt><dd>{clock(r.promise)}</dd>
          <dt>Station</dt><dd style={{ textTransform: "capitalize" }}>{r.station || "–"}</dd>
          {r.customer_distance_km !== null && r.customer_distance_km !== undefined && <><dt>Customer</dt><dd>{r.customer_distance_km.toFixed(1)} km</dd></>}
        </dl>
      </div>
    </div>
  );
}

/* ================= kitchen timeline ================= */

export function KitchenTimeline({ stations, nowMin, chOf, hover, setHover, onPick }: {
  stations: Station[]; nowMin: number; chOf: (id: string) => string | undefined; hover: string | null; setHover: (id: string | null) => void; onPick: (id: string) => void;
}) {
  const t0 = Math.floor((nowMin - 10) / 5) * 5, t1 = t0 + 55;
  const x = (m: number) => ((m - t0) / (t1 - t0)) * 100;
  const ticks = Array.from({ length: 12 }, (_, i) => t0 + i * 5).filter((m) => m % 10 === 0);
  return (
    <div className="ktl" data-testid="timeline">
      <div className="ktl-axis">{ticks.map((m) => <span key={m} className="num" style={{ left: `${x(m)}%` }}>{clock(fromMin(m)).replace(" pm", "").replace(" am", "")}</span>)}</div>
      {stations.map((s) => (
        <div key={s.key} className="ktl-lane">
          <b>{s.name}{s.speed < 1 && <span className="crit"> · {s.speed <= 0 ? "down" : `${Math.round(s.speed * 100)}% speed`}</span>}</b>
          <div className="ktl-track">
            {s.tasks.map((t) => {
              const a = toMin(t.start), b = Math.max(toMin(t.end), a + 0.6);
              if (b < t0 || a > t1) return null;
              const ch = t.channel || chOf(t.order_id) || "";
              const left = x(Math.max(t0, a)), width = x(Math.min(t1, b)) - left;
              return (
                <button key={`${t.order_id}-${t.item}-${t.start}`} className={`ktask${t.frozen ? " frozen" : ""}${hover === t.order_id ? " hov" : ""}`}
                  style={{ left: `${left}%`, width: `calc(${width}% - 2px)`, ["--c" as string]: CH_COLOR[ch] || "#56605b" }}
                  onMouseEnter={() => setHover(t.order_id)} onMouseLeave={() => setHover(null)} onClick={() => onPick(t.order_id)}
                  title={`${t.order_id} · ${t.item} · ${clock(t.start)}–${clock(t.end)}${t.frozen ? " · on the line" : ""}`} aria-label={`${t.order_id} ${t.item}`}>
                  {width > 5 ? t.item : ""}
                </button>
              );
            })}
            <span className="ktl-now" style={{ left: `${x(nowMin)}%` }} />
          </div>
        </div>
      ))}
    </div>
  );
}

/* ================= Gondola vs first-come ================= */

export function ComparePanel({ c, n }: { c: { fifo: CompareSide; gondola: CompareSide } | null; n?: number }) {
  if (!c) return <Skeleton h={180} />;
  const rows: [string, keyof CompareSide, (v: number) => string, boolean][] = [
    ["Promises met", "promises_met", (v) => `${Math.round((v <= 1 ? v * 100 : v))}%`, true],
    ["Average wait", "avg_wait", (v) => `${v.toFixed(1)} min`, false],
    ["Worst wait", "worst_wait", (v) => `${v.toFixed(1)} min`, false],
    ["Food hold", "hold", (v) => `${v.toFixed(1)} min`, false],
  ];
  return (
    <div className="cmp" data-testid="compare">
      <div className="cmp-key"><span><i className="sw" style={{ background: "var(--green)" }} />Gondola</span><span><i className="sw" style={{ background: "#c3cbc5" }} />First-come</span>{n ? <span className="ink2 num">{n} orders</span> : null}</div>
      {rows.map(([label, k, f, higher]) => {
        const g = c.gondola[k] as number | null, q = c.fifo[k] as number | null;
        if (g === null || g === undefined || q === null || q === undefined) return <div key={k} className="cmp-row"><span>{label}</span><span className="ink2">–</span></div>;
        const max = Math.max(g, q, 1e-6) * (k === "promises_met" ? 1 : 1.1);
        const better = higher ? g >= q : g <= q;
        return (
          <div key={k} className="cmp-row" data-k={k}>
            <span>{label}</span>
            <span className="cmp-bars">
              <span><i style={{ width: `${(g / max) * 100}%`, background: "var(--green)" }} /></span>
              <span><i style={{ width: `${(q / max) * 100}%`, background: "#c3cbc5" }} /></span>
            </span>
            <span className="cmp-v num"><b className={better ? "good" : "crit"}>{f(g)}</b><span className="ink2">{f(q)}</span></span>
          </div>
        );
      })}
    </div>
  );
}

/* ================= recent actions ================= */

const BY: Record<string, string> = { controller: "Controller", "rush-agent": "Rush agent", manager: "Manager", pricing: "Pricing" };
export function ActionList({ actions, max = 8 }: { actions: Action[]; max?: number }) {
  if (!actions.length) return <div className="ink2" style={{ padding: "8px 0" }}>No actions yet today</div>;
  return (
    <div className="alist" data-testid="actions">
      {actions.slice(0, max).map((a, i) => (
        <div key={`${a.ts}-${a.action}-${i}`} className={`aitem enter${a.by === "rush-agent" ? " agent" : ""}`} data-actor={actor(a)}>
          <span className="num muted">{a.ts ? clock(a.ts.slice(11, 16)) : a.time ? clock(a.time) : ""}</span>
          <div>
            <div className="ahead"><b>{actionText(a)}</b>{a.headroom_pct !== null && a.headroom_pct !== undefined && <span className="num ink2">{fmtPct(a.headroom_pct)}</span>}</div>
            {(a.reason || (a.by && a.by !== "controller")) && <div className="ink2 areason">{a.by && a.by !== "controller" ? `${BY[a.by] || a.by}: ` : ""}{(a.reason || "").replace(/->/g, "→")}</div>}
            {a.receipt_id && <div className="muted areason">Receipt {a.receipt_id}</div>}
          </div>
        </div>
      ))}
    </div>
  );
}

/* ================= settings drawer ================= */

export function SettingsDrawer({ open, onClose, onSaved }: { open: boolean; onClose: () => void; onSaved: (s: PresentSettings) => void }) {
  const [s, setS] = useState<PresentSettings | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => { if (open) { setErr(null); tri.present.settings().then(setS).catch((e) => { setErr(String(e.message)); setS(DEFAULT_SETTINGS); }); } }, [open]);
  const L = s?.ladder;
  const setL = (k: keyof PresentSettings["ladder"], v: number) => setS((x) => (x ? { ...x, ladder: { ...x.ladder, [k]: v } } : x));
  const valid = !!L && L.promote_above > L.quote_below && L.quote_below > L.pause_below && L.pause_below > L.busy_below;
  const save = async () => {
    if (!s) return;
    setBusy(true); setErr(null);
    try { const r = await tri.present.saveSettings(s); onSaved(r && r.ladder ? r : s); onClose(); }
    catch (e) { setErr(String((e as Error).message)); }
    finally { setBusy(false); }
  };
  return (
    <Drawer open={open} onClose={onClose} label="Ladder settings" width={480}>
      <h2>Ladder and queue</h2>
      {!s && <Skeleton h={300} />}
      {s && L && <>
        <div className="setgroup" data-testid="settings">
          <h4>Ladder thresholds<Info k="ladder" inline /></h4>
          {([["promote_above", "Promote above"], ["quote_below", "Quote longer below"], ["pause_below", "Pause slow items below"], ["busy_below", "Busy mode below"]] as const).map(([k, label]) => (
            <label key={k} className="setrow"><span>{label}</span>
              <span className="setval"><input type="number" className="input slim num" step={1} min={-60} max={60} value={L[k]} aria-label={label} name={k}
                onChange={(e) => setL(k, Number(e.target.value))} onKeyDown={(e) => e.stopPropagation()} />%</span></label>
          ))}
          <label className="setrow"><span>Hold a step at least</span>
            <span className="setval"><input type="number" className="input slim num" step={1} min={0} max={15} value={L.hysteresis_min} aria-label="Hysteresis minutes" name="hysteresis_min"
              onChange={(e) => setL("hysteresis_min", Number(e.target.value))} onKeyDown={(e) => e.stopPropagation()} />min</span></label>
          {!valid && <div className="crit" style={{ fontSize: 13.5 }}>Each threshold must be below the one above it</div>}
        </div>
        <div className="setgroup">
          <h4>Queue weights<Info k="factors" inline /></h4>
          {Object.entries(s.weights).filter(([k]) => (FACTOR_KEYS as readonly string[]).includes(k)).map(([k, v]) => (
            <label key={k} className="setrow wt"><span>{FACTOR_NAME[k] || k.replace(/_/g, " ")}</span>
              <input type="range" className="range light" min={0} max={Math.max(2, Math.ceil(v))} step={0.1} value={v} aria-label={`${FACTOR_NAME[k] || k} weight`}
                onChange={(e) => setS((x) => (x ? { ...x, weights: { ...x.weights, [k]: Number(e.target.value) } } : x))} />
              <b className="num">{v.toFixed(1)}</b></label>
          ))}
          {Object.entries(s.weights).filter(([k, v]) => !(FACTOR_KEYS as readonly string[]).includes(k) && typeof v === "number").map(([k, v]) => (
            <label key={k} className="setrow"><span>{PARAM_NAME[k] || k.replace(/_/g, " ").replace(/ min$/, "")}</span>
              <span className="setval"><input type="number" className="input slim num" step={/temp|factor/.test(k) ? 0.1 : 0.5} value={v} aria-label={k} name={k}
                onChange={(e) => setS((x) => (x ? { ...x, weights: { ...x.weights, [k]: Number(e.target.value) } } : x))} onKeyDown={(e) => e.stopPropagation()} />{/_min$/.test(k) ? "min" : /_c$/.test(k) ? "°C" : ""}</span></label>
          ))}
          <label className="setrow"><span>Longest any order may wait</span>
            <span className="setval"><input type="number" className="input slim num" min={5} max={90} value={s.max_wait_min} aria-label="Max wait minutes" name="max_wait_min"
              onChange={(e) => setS((x) => (x ? { ...x, max_wait_min: Number(e.target.value) } : x))} onKeyDown={(e) => e.stopPropagation()} />min</span></label>
        </div>
        {err && <ErrorBox error={err} />}
        <div style={{ display: "flex", gap: 10, justifyContent: "flex-end" }}>
          <button className="btn light" onClick={() => setS(DEFAULT_SETTINGS)}>Defaults</button>
          <button className="btn" onClick={save} disabled={busy || !valid}>{busy ? "Saving" : "Save"}</button>
        </div>
      </>}
    </Drawer>
  );
}

export function useCompare(date: string, live: boolean) {
  const [c, setC] = useState<Compare | null>(null);
  useEffect(() => {
    let dead = false;
    setC(null);
    const pull = () => tri.present.compare(date).then((x) => { if (!dead) setC(x); }).catch(() => {});
    if (date) pull();
    const id = live ? setInterval(pull, 60000) : undefined;
    return () => { dead = true; if (id) clearInterval(id); };
  }, [date, live]);
  return c;
}

export const useChannelOf = (rows: QueueRow[]) => useMemo(() => { const m = new Map(rows.map((r) => [r.order_id, r.channel])); return (id: string) => m.get(id); }, [rows]);
