/** Present › Cook order: a status board a busy cook can read at a glance.
 *
 *  Orders move left to right through four columns: New → Up next → Cooking → Ready.
 *  New orders sit in "New" for a few seconds while Gondola sorts them, then appear in "Up next" at the spot its
 *  queue chose (slack-based ranking, gondola/present/queue.py). Cards never glide around: a change of place is shown
 *  with a soft highlight and a short "Moved up" tag. Tap any card for its details and why it's in that spot.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import type { QueueRow } from "../api/tri";
import { Page } from "../components/Page";
import { CH_COLOR, Drawer, ErrorBox, Skeleton } from "../components/ui";
import { StatusBar, chName, hm, isLate, itemsText, num, ordinal, tone, usePresentState } from "../components/peak";
import { fromMin, toMin } from "../lib/dates";

const SORT_MS = 3500;   // how long a new order stays in "New"
const TAG_MS = 5000;    // how long "New" / "Moved up" highlights stay
type Row = QueueRow & { created?: string | null; due_source?: string; planned_start?: string | null };

/* ---------- plain-language reasons ---------- */
function headline(r: Row): string {
  const f = r.factors || {};
  if (isLate(r)) return (r.predicted_late_min ?? 0) > 0 ? `Running ${r.predicted_late_min} min late` : "Behind schedule";
  if (r.courier_arrived) return "Driver is already here";
  if (r.fulfillment === "dine_in") return "Guest is seated in the store";
  if (r.customer_present) return "Customer waiting at the counter";
  if (num(f.courier) < 0) return "Driver arriving soon";
  if (num(f.fairness) < 0) return "Has been waiting a long time";
  if (r.slack_min !== null && r.slack_min < 5) return "Due very soon";
  if (num(f.batch) < 0) return "Cook together with the same dish";
  if (num(f.courier) > 0) return "Driver is still far away — can wait";
  if (num(f.hold) > 0) return "Cook closer to pickup so it stays fresh";
  if (num(f.distance) > 0) return "Long drive — finish close to pickup";
  return r.due ? `Due at ${hm(r.due)}` : "In line";
}
/** Each factor the queue applied, as a sentence and its push in minutes (− = earlier, + = later). */
function factorLines(r: Row): { text: string; min: number }[] {
  const f = r.factors || {};
  const out: { text: string; min: number }[] = [];
  const c = num(f.courier);
  if (c < 0) out.push({ text: r.courier_arrived ? "Driver is already at the store" : `Driver arriving${r.courier_eta ? ` at ${hm(r.courier_eta)}` : " now"}`, min: c });
  if (c > 0) out.push({ text: `Driver gets here after the promised time${r.courier_eta ? ` (${hm(r.courier_eta)})` : ""}, so it can wait`, min: c });
  if (num(f.in_store) < 0) out.push({ text: r.fulfillment === "dine_in" ? "Guest is seated in the store" : "Customer is waiting at the counter", min: num(f.in_store) });
  if (num(f.fairness) < 0) out.push({ text: "Has waited a long time — fairness limit pulls it forward", min: num(f.fairness) });
  if (num(f.weather) < 0) out.push({ text: "Rain or snow makes drivers less predictable — be ready earlier", min: num(f.weather) });
  if (num(f.batch) < 0) out.push({ text: "Same dish as orders next to it — cook them together", min: num(f.batch) });
  if (num(f.hold) > 0) out.push({ text: "Doesn't hold well once cooked — start it closer to pickup", min: num(f.hold) });
  if (num(f.distance) > 0) out.push({ text: `Long drive to the customer${r.customer_distance_km ? ` (${r.customer_distance_km.toFixed(1)} km)` : ""} — finish close to pickup`, min: num(f.distance) });
  return out.filter((l) => Math.abs(l.min) >= 0.5).sort((a, b) => Math.abs(b.min) - Math.abs(a.min));
}

/* ---------- arrivals and moves, tracked between updates ---------- */
function useBoardTracking(waiting: Row[], nowMin: number, reset: string) {
  const seen = useRef<Set<string> | null>(null);
  const prevRank = useRef(new Map<string, number>());
  const timers = useRef<ReturnType<typeof setTimeout>[]>([]);
  const [sorting, setSorting] = useState<Set<string>>(new Set());
  const [fresh, setFresh] = useState<Map<string, number>>(new Map());   // id -> how many earlier orders it went ahead of
  const [moved, setMoved] = useState<Map<string, number>>(new Map());   // id -> places moved (+ up, - down)
  useEffect(() => () => timers.current.forEach(clearTimeout), []);
  useEffect(() => { seen.current = null; prevRank.current = new Map(); setSorting(new Set()); setFresh(new Map()); setMoved(new Map()); }, [reset]);
  const later = (ms: number, f: () => void) => timers.current.push(setTimeout(f, ms));
  const key = waiting.map((r) => `${r.order_id}:${r.rank}`).join("|");
  useEffect(() => {
    const ranked = [...waiting].sort((a, b) => a.rank - b.rank).map((r) => r.order_id);
    const pos = new Map(ranked.map((id, i) => [id, i + 1]));
    if (seen.current === null) { seen.current = new Set(ranked); prevRank.current = pos; return; }
    // new = not seen before and received in the last 2 store minutes (a clock jump never floods "New")
    const arrivals = waiting.filter((r) => !seen.current!.has(r.order_id) && r.created && nowMin - toMin(r.created) <= 2).map((r) => r.order_id);
    ranked.forEach((id) => seen.current!.add(id));
    if (arrivals.length) {
      setSorting((p) => new Set([...p, ...arrivals]));
      later(SORT_MS, () => {
        setSorting((p) => { const n = new Set(p); arrivals.forEach((id) => n.delete(id)); return n; });
        setFresh((p) => { const n = new Map(p); arrivals.forEach((id) => n.set(id, 1)); return n; });
        later(TAG_MS, () => setFresh((p) => { const n = new Map(p); arrivals.forEach((id) => n.delete(id)); return n; }));
      });
    }
    // Real re-prioritisation only: compare order among the orders present in both updates, so a new order slotting
    // in (or one leaving for the line) never makes the others look "moved". Only jumps up by 2+ get a tag.
    const common = ranked.filter((id) => prevRank.current.has(id));
    const before = [...common].sort((a, b) => prevRank.current.get(a)! - prevRank.current.get(b)!);
    const changes = new Map<string, number>();
    common.forEach((id, i) => { const d = before.indexOf(id) - i; if (d >= 2) changes.set(id, d); });
    prevRank.current = pos;
    if (changes.size) {
      setMoved((m) => new Map([...m, ...changes]));
      later(TAG_MS, () => setMoved((m) => { const n = new Map(m); changes.forEach((_, id) => n.delete(id)); return n; }));
    }
  }, [key]); // eslint-disable-line react-hooks/exhaustive-deps
  return { sorting, fresh, moved };
}

export default function Peak() {
  const { st, error, retry, date, playback, closed } = usePresentState();
  const queue = (st?.queue || []) as Row[];
  const waiting = useMemo(() => queue.filter((r) => r.status === "queued"), [queue]);
  const cooking = useMemo(() => queue.filter((r) => r.status === "cooking" || r.status === "packing").sort((a, b) => String(a.planned_ready || "").localeCompare(String(b.planned_ready || ""))), [queue]);
  const ready = useMemo(() => queue.filter((r) => r.status === "ready").sort((a, b) => Number(!!b.courier_arrived || !!b.customer_present) - Number(!!a.courier_arrived || !!a.customer_present)), [queue]);
  const nowMin = st ? toMin(st.now) : 0;
  const { sorting, fresh, moved } = useBoardTracking(waiting, nowMin, `${date}|${playback.active}`);
  const arrived = useMemo(() => new Map([...waiting].sort((a, b) => String(a.created || "").localeCompare(String(b.created || "")) || a.order_id.localeCompare(b.order_id)).map((r, i) => [r.order_id, i + 1])), [waiting]);
  const newOnes = waiting.filter((r) => sorting.has(r.order_id));
  const upNext = useMemo(() => waiting.filter((r) => !sorting.has(r.order_id)).sort((a, b) => a.rank - b.rank), [waiting, sorting]);
  const [open, setOpen] = useState<string | null>(null);
  const sel = queue.find((r) => r.order_id === open) || null;
  const style = (r: Row) => ({ ["--ch" as any]: CH_COLOR[r.channel] || "#888" });

  return (
    <Page title="Present" date={false}>
      {error && <ErrorBox error={error} retry={retry} />}
      {!st && !error && <><Skeleton h={88} /><Skeleton h={480} /></>}
      {st && <>
        <StatusBar st={st} closed={closed} />
        <div className="bd">
          <Col title="New" n={newOnes.length} hint="Being sorted" cls="new">
            {newOnes.length === 0 && <p className="bd-empty">New orders appear here</p>}
            {newOnes.map((r) => (
              <article key={r.order_id} className="bd-card sorting" style={style(r)}>
                <div className="pk-top"><Chan c={r.channel} /><span className="pk-id">#{r.order_id}</span></div>
                <div className="bd-items">{itemsText(r.items)}</div>
                <div className="bd-sorting"><span className="pk-spin" aria-hidden />Finding its spot…</div>
              </article>
            ))}
          </Col>

          <Col title="Up next" n={upNext.length} hint="Cook from the top" cls="next">
            {upNext.length === 0 && <p className="bd-empty">{closed ? "Service has ended." : "Nothing waiting to cook."}</p>}
            {upNext.map((r, i) => {
              const c = i + 1;
              const t = tone(r);
              const ahead = fresh.has(r.order_id) ? Math.max(0, (arrived.get(r.order_id) || c) - c) : 0;
              const mv = moved.get(r.order_id);
              return (
                <button key={r.order_id} className={`bd-card q ${t} ${c === 1 ? "first" : ""} ${fresh.has(r.order_id) ? "hl" : ""}`} style={style(r)} onClick={() => setOpen(r.order_id)}
                  aria-label={`Up next ${c}: order ${r.order_id}, ${itemsText(r.items)}. ${headline(r)}. Show details.`}>
                  <span className="bd-rank num">{c}</span>
                  <div className="bd-main">
                    <div className="pk-top">
                      {c === 1 && <span className="pk-next">Cook next</span>}
                      <Chan c={r.channel} /><span className="pk-id">#{r.order_id}</span>
                      {fresh.has(r.order_id) && <span className="bd-tag new">New{ahead > 0 ? ` · ahead of ${ahead} earlier` : ""}</span>}
                      {mv !== undefined && <span className="bd-tag up">▲ Moved up {mv}</span>}
                    </div>
                    <div className="bd-items">{itemsText(r.items)}</div>
                    <div className={`pk-why ${t}`}>{headline(r)}</div>
                  </div>
                  <span className="bd-time num">{r.planned_start ? <>start<b>{hm(r.planned_start)}</b></> : r.due ? <>due<b>{hm(r.due)}</b></> : null}</span>
                </button>
              );
            })}
          </Col>

          <Col title="Cooking" n={cooking.length} hint="On the line" cls="cook">
            {cooking.length === 0 && <p className="bd-empty">Nothing on the line.</p>}
            {cooking.map((r) => (
              <button key={r.order_id} className={`bd-card s ${isLate(r) ? "late" : ""}`} style={style(r)} onClick={() => setOpen(r.order_id)}>
                <div className="pk-top"><Chan c={r.channel} /><span className="pk-id">#{r.order_id}</span></div>
                <div className="bd-items sm">{itemsText(r.items)}</div>
                <div className="bd-foot"><span className={`bd-pill ${r.status}`}>{r.status === "packing" ? "Packing" : "Cooking"}</span>{r.planned_ready && <span className="num">ready {hm(r.planned_ready)}</span>}</div>
              </button>
            ))}
          </Col>

          <Col title="Ready" n={ready.length} hint="Hand off" cls="ready">
            {ready.length === 0 && <p className="bd-empty">Nothing waiting for pickup.</p>}
            {ready.map((r) => {
              const here = r.courier_arrived || r.customer_present || r.fulfillment === "dine_in";
              const who = r.fulfillment === "delivery" ? (r.courier_arrived ? "Driver is here" : r.courier_eta ? `Driver ${hm(r.courier_eta)}` : "Waiting for driver")
                : r.fulfillment === "dine_in" ? "Serve to table" : r.customer_present ? "Customer is here" : "Customer coming";
              return (
                <button key={r.order_id} className={`bd-card s ${here ? "here" : ""}`} style={style(r)} onClick={() => setOpen(r.order_id)}>
                  <div className="pk-top"><Chan c={r.channel} /><span className="pk-id">#{r.order_id}</span></div>
                  <div className="bd-items sm">{itemsText(r.items)}</div>
                  <div className="bd-foot"><span className={`bd-pill ${here ? "here" : "wait"}`}>{who}</span></div>
                </button>
              );
            })}
          </Col>
        </div>
      </>}
      <Drawer open={!!sel} onClose={() => setOpen(null)} label="Order details" width={460}>
        {sel && <OrderDetail r={sel} pos={sel.status === "queued" ? (upNext.findIndex((x) => x.order_id === sel.order_id) + 1 || null) : null} arrivedAt={arrived.get(sel.order_id) || null} nowMin={nowMin} />}
      </Drawer>
    </Page>
  );
}

function Col({ title, n, hint, cls, children }: { title: string; n: number; hint: string; cls: string; children: React.ReactNode }) {
  return (
    <section className={`bd-col ${cls}`} aria-label={title}>
      <header><h2>{title}</h2><span className="bd-n num">{n}</span><span className="bd-hint">{hint}</span></header>
      <div className="bd-stack">{children}</div>
    </section>
  );
}
function Chan({ c }: { c: string }) {
  return <span className="pk-chan" style={{ background: CH_COLOR[c] || "#888" }}>{chName(c)}</span>;
}

const STAGES = [["queued", "Waiting"], ["cooking", "Cooking"], ["packing", "Packing"], ["ready", "Ready"]] as const;
const DUE_WORD: Record<string, string> = { promise: "promised time", "courier ETA": "driver arrives", "guest here": "customer is here", "courier here": "driver is here" };

function OrderDetail({ r, pos, arrivedAt, nowMin }: { r: Row; pos: number | null; arrivedAt: number | null; nowMin: number }) {
  const lines = factorLines(r);
  const t = tone(r);
  const maxAbs = Math.max(4, ...lines.map((l) => Math.abs(l.min)));
  const stage = STAGES.findIndex(([k]) => k === r.status);
  const steps = [
    { k: "Came in", t: r.created }, { k: "Start cooking by", t: r.status === "queued" ? r.latest_start : null },
    { k: r.status === "ready" ? "Was ready" : "Ready at", t: r.planned_ready }, { k: `Due (${DUE_WORD[r.due_source || ""] || "promised time"})`, t: r.due },
  ].filter((x) => !!x.t).map((x) => ({ ...x, m: toMin(x.t!) })).sort((a, b) => a.m - b.m);
  const nowAt = steps.findIndex((x) => x.m > nowMin);
  return (
    <div className="od">
      <div className="od-head" style={{ ["--ch" as any]: CH_COLOR[r.channel] || "#888" }}>
        <div className="pk-top"><Chan c={r.channel} /><span className="pk-id">#{r.order_id}</span></div>
        <h2>{itemsText(r.items)}</h2>
      </div>

      <ol className="od-stages">
        {STAGES.map(([k, label], i) => <li key={k} className={i < stage ? "done" : i === stage ? "on" : ""}>{label}</li>)}
      </ol>

      {pos && <div className={`od-place ${t}`}>
        <b>#{pos} up next</b>
        <span>{arrivedAt && arrivedAt !== pos ? `It arrived ${ordinal(arrivedAt)}. Gondola moved it ${arrivedAt > pos ? `up ${arrivedAt - pos}` : `down ${pos - arrivedAt}`}.` : "Same spot as it arrived."}</span>
      </div>}

      <div>
        <h3>Timing</h3>
        <ul className="od-steps num">
          {steps.map((x, i) => [
            i === nowAt ? <li key="now" className="od-nowonly"><div className="od-nowrow"><span>now · {fromMin(nowMin)}</span></div></li> : null,
            <li key={x.k} className={`${x.m <= nowMin ? "past" : ""} ${x.k.startsWith("Due") ? "due" : ""}`}><span className="od-k">{x.k}</span><b>{hm(x.t)}</b></li>,
          ])}
          {nowAt === -1 && <li className="od-nowonly"><div className="od-nowrow"><span>now · {fromMin(nowMin)}</span></div></li>}
        </ul>
        {r.status === "queued" && r.slack_min !== null && <p className={`od-slack ${t}`}>{r.slack_min >= 0 ? `${Math.round(r.slack_min)} min to spare before it has to start.` : `${Math.round(-r.slack_min)} min past when it should have started.`}</p>}
        <dl className="od-facts num">
          <div><dt>Promised</dt><dd>{hm(r.promise) || "—"}{r.quoted_extra_min ? ` (+${r.quoted_extra_min})` : ""}</dd></div>
          {r.fulfillment === "delivery" ? <div><dt>Driver</dt><dd>{r.courier_arrived ? "Here now" : r.courier_eta ? `Arrives ${hm(r.courier_eta)}` : "Not assigned yet"}{r.courier_distance_km ? ` · ${r.courier_distance_km.toFixed(1)} km` : ""}</dd></div>
            : <div><dt>Customer</dt><dd>{r.fulfillment === "dine_in" ? "Seated" : r.customer_present ? "At the counter" : "On the way"}</dd></div>}
        </dl>
      </div>

      {r.status === "queued" && <div className="od-why">
        <h3>Why it's in this spot</h3>
        <p className="ink2">Orders with the least time to spare go first. These nudged it:</p>
        {lines.length === 0 && <p>Nothing special — placed by its due time alone.</p>}
        <ul>
          {lines.map((l) => (
            <li key={l.text}>
              <span>{l.text}</span>
              <span className={`od-bar ${l.min < 0 ? "early" : "later"}`}><i style={{ width: `${(Math.abs(l.min) / maxAbs) * 100}%` }} /></span>
              <b className="num">{l.min < 0 ? "sooner" : "later"} {Math.round(Math.abs(l.min))} min</b>
            </li>
          ))}
        </ul>
        <p className="od-note">Which app an order came from never changes its place.</p>
      </div>}
    </div>
  );
}
