import { useEffect, useRef, useState } from "react";
import { flexApi, FlexError, type FlexCart, type FlexConfig, type FlexJob, type FlexOption, type FlexQuote, type FlexReceipt, type FlexSession, type FlexTask } from "../api/flex";
import { rushApi } from "../api/rush";
import { Icon } from "../components/ui";
import "../rush.css";
import "../flex.css";

const money = (c: number) => `$${(c / 100).toFixed(2)}`;
const clock = (m: number) => `${String(Math.floor((1050 + m) / 60)).padStart(2, "0")}:${String((1050 + m) % 60).padStart(2, "0")}`;
const stationNames: Record<string, string> = { fryer: "Fryer", noodles: "Noodles", assembly: "Assembly", packing: "Packing" };
const initialConfig: FlexConfig = { scenario: "rush", seed: 7, cooks: 3, budget_cents: 1200, max_discount_cents: 300, quote_ttl_seconds: 180 };
const toolNames: Record<string, string> = { inspect_checkout: "Read your preferences and current kitchen reservations", compare_pickup_choices: "Compared feasible times, savings and capacity relief", check_pickup_choice: "Checked a time and incentive against the limits", publish_pickup_choices: "Published checked choices for your decision", publish_regular_only: "Kept regular pickup; a discount was not justified" };

function MealArt({ item = "don" }: { item?: string }) {
  const fried = item === "karaage" || item === "gyoza";
  return <svg viewBox="0 0 230 145" aria-hidden="true"><ellipse cx="115" cy="125" rx="83" ry="10" fill="#213c2610" /><path d="M33 65h164c-7 40-32 53-82 53S39 105 33 65" fill={fried ? "#c28b59" : "#c2d1ac"} /><ellipse cx="115" cy="65" rx="82" ry="30" fill="#f9f2d6" /><ellipse cx="115" cy="65" rx="70" ry="23" fill={fried ? "#b77e43" : "#b0bd77"} /><path d="M56 59q12-18 27 0t27 0t27 0t27 0M61 72q12-18 27 0t27 0t27 0t27 0" stroke="#f2e1a9" strokeWidth="6" strokeLinecap="round" fill="none" /><ellipse cx="139" cy="61" rx="30" ry="15" fill="#a36a4e" transform="rotate(-18 139 61)" /><ellipse cx="140" cy="60" rx="19" ry="9" fill="#ce9b7a" transform="rotate(-18 140 60)" /><circle cx="82" cy="62" r="10" fill="#68834d" /><circle cx="94" cy="48" r="8" fill="#68834d" /><path d="M106 22q-10-10 0-20M126 25q-10-10 0-20" stroke="#96a785" strokeWidth="2" strokeLinecap="round" fill="none" /></svg>;
}

export default function Flex() {
  const [session, setSession] = useState<FlexSession | null>(null);
  const [config, setConfig] = useState<FlexConfig>(initialConfig);
  const [cart, setCart] = useState<FlexCart>({ cart_id: crypto.randomUUID(), item: "don", latest_pickup_minute: 70, minimum_saving_cents: 200 });
  const [quote, setQuote] = useState<FlexQuote | null>(null);
  const [selected, setSelected] = useState("");
  const [receipt, setReceipt] = useState<FlexReceipt | null>(null);
  const [view, setView] = useState(new URLSearchParams(location.search).get("view") === "merchant" ? "merchant" : "shopper");
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [now, setNow] = useState(Date.now() / 1000);
  const [agentAvailable, setAgentAvailable] = useState(false);
  const [job, setJob] = useState<FlexJob | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [stale, setStale] = useState(false);
  const generation = useRef(0);

  function adoptQuote(q: FlexQuote) { setQuote(q); setSelected(q.options[1]?.id || q.options[0]?.id || ""); setStale(false); sessionStorage.setItem(`flex-quote-${session?.id}`, q.id); }
  async function startEpisode(next = config) {
    setBusy(true); setError(""); setQuote(null); setReceipt(null); setJob(null); setStale(false);
    try { const s = await flexApi.create(next); setSession(s); setConfig(s.config); localStorage.setItem("flex-session", s.id); history.replaceState({}, "", `/flex?s=${s.id}`); const c = { ...cart, cart_id: crypto.randomUUID() }; setCart(c); sessionStorage.setItem(`flex-cart-${s.id}`, JSON.stringify(c)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  useEffect(() => {
    let mounted = true;
    const gen = ++generation.current;
    const query = new URLSearchParams(location.search);
    const saved = query.get("s") || localStorage.getItem("flex-session");
    rushApi.config().then(c => mounted && setAgentAvailable(c.agent_configured)).catch(() => {});
    async function init() {
      try {
        const s = saved ? await flexApi.session(saved) : await flexApi.create(initialConfig);
        if (!mounted || gen !== generation.current) return;
        setSession(s); setConfig(s.config); localStorage.setItem("flex-session", s.id);
        const raw = !query.has("new") && sessionStorage.getItem(`flex-cart-${s.id}`);
        const c = raw ? JSON.parse(raw) as FlexCart : { cart_id: crypto.randomUUID(), item: "don", latest_pickup_minute: 70, minimum_saving_cents: 200 };
        setCart(c); sessionStorage.setItem(`flex-cart-${s.id}`, JSON.stringify(c));
        const b = s.bookings.find(b => b.cart_id === c.cart_id); if (b) setReceipt(b);
        const qid = !query.has("new") && sessionStorage.getItem(`flex-quote-${s.id}`);
        if (qid && !b) { const q = await flexApi.getQuote(s.id, qid); if (mounted) { setQuote(q); setSelected(q.options[1]?.id || q.options[0]?.id || ""); } }
        history.replaceState({}, "", `/flex?s=${s.id}${view === "merchant" ? "&view=merchant" : ""}`);
      } catch (e) { if (mounted) setError(`${(e as Error).message}. Start a new demo episode to reconnect.`); }
      finally { if (mounted) setBusy(false); }
    }
    void init();
    return () => { mounted = false; generation.current++; };
  }, []);
  useEffect(() => { const id = setInterval(() => setNow(Date.now() / 1000), 1000); return () => clearInterval(id); }, []);
  useEffect(() => {
    if (!session) return;
    const id = setInterval(() => { flexApi.session(session.id).then(setSession).catch(() => {}); }, 2000);
    return () => clearInterval(id);
  }, [session?.id]);
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    const poll = async () => {
      try { const j = await flexApi.job(jobId); if (stopped) return; setJob(j); if (j.status !== "running") { setJobId(null); if (j.status === "done" && j.result) { adoptQuote(j.result.quote); setSession(j.result.session); } else setError(j.error || "The agent did not publish choices. No result is being claimed."); } }
      catch (e) { if (!stopped) { setError((e as Error).message); setJobId(null); } }
    };
    void poll(); const id = setInterval(poll, 900); return () => { stopped = true; clearInterval(id); };
  }, [jobId]);

  const chosen = quote?.options.find(o => o.id === selected) || quote?.options[0];
  const regular = quote?.options[0];
  const seconds = quote ? Math.max(0, Math.ceil(quote.expires_at - now)) : 0;
  const expired = !!quote && (seconds <= 0 || quote.status !== "open" || stale);
  const locked = busy || !!jobId;
  const pending = session?.base_orders.filter(o => o.ready === null).length || 0;
  // An owner opening the shared ledger can inspect its latest confirmed order,
  // without adopting that customer's receipt in their own checkout.
  const evidenceReceipt = receipt || (!quote ? session?.bookings.filter(b => b.comparison).slice(-1)[0] : undefined);
  const displayChoice = evidenceReceipt?.option || chosen;
  const displayRegular = evidenceReceipt?.regular_option || regular;
  const compareAlloc = evidenceReceipt?.comparison?.allocations || quote?.baseline_allocations || [];
  const timelineEnd = Math.max(65, (displayChoice?.pickup_minute || 0) + 5, (displayRegular?.pickup_minute || 0) + 5);

  function updateCart(next: FlexCart) { setCart(next); setQuote(null); setJob(null); setError(""); setStale(false); if (session) { sessionStorage.setItem(`flex-cart-${session.id}`, JSON.stringify(next)); sessionStorage.removeItem(`flex-quote-${session.id}`); } }
  async function find(useAgent = false) {
    if (!session) return;
    setError(""); setBusy(true); setReceipt(null); setQuote(null); setJob(null);
    try { if (useAgent) { const r = await flexApi.agent(session.id, cart); setJobId(r.id); } else adoptQuote(await flexApi.quote(session.id, cart)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }
  async function confirm() {
    if (!session || !quote || !chosen) return;
    setBusy(true); setError("");
    try { const r = await flexApi.accept(session.id, quote.id, chosen.id); setReceipt(r); setSession(await flexApi.session(session.id)); }
    catch (e) { setError((e as Error).message); if (e instanceof FlexError && e.status === 409) setStale(true); }
    finally { setBusy(false); }
  }
  async function decline() {
    if (!session || !quote) return;
    try { await flexApi.decline(session.id, quote.id); setQuote(null); setError(""); sessionStorage.removeItem(`flex-quote-${session.id}`); } catch (e) { setError((e as Error).message); }
  }
  async function compete() {
    if (!session || !quote || !chosen) return;
    setBusy(true); setError("");
    try { await flexApi.compete(session.id, quote.id, chosen.id); setSession(await flexApi.session(session.id)); }
    catch (e) { setError((e as Error).message); }
    finally { setBusy(false); }
  }

  return <div className="rush flex" data-testid="flex-workspace">
    <header className="rush-head"><div><span className="rush-eyebrow">HANABI RAMEN / FLEXIBLE PICKUP</span><h1>A little later<span>.</span><br />A little less.</h1></div><div className="rush-source"><span className="rush-pill">Simulated checkout · no payment</span><a className="flex-back" href="/rush">Rush control ↗</a></div></header>
    <div className="flex-nav"><div className="rush-tabs"><button className={view === "shopper" ? "on" : ""} onClick={() => setView("shopper")}>Customer checkout</button><button className={view === "merchant" ? "on" : ""} onClick={() => setView("merchant")}>Kitchen & evidence</button></div><span className="rush-tiny">Demo views share one reservation ledger</span><details className="flex-setup"><summary>Demo setup</summary><div><label>Episode<select aria-label="Flex scenario" value={config.scenario} onChange={e => setConfig({ ...config, scenario: e.target.value })}><option value="rush">Event-night rush</option><option value="quiet">Quiet evening</option><option value="overload">Beyond capacity</option></select></label><label>Cooks<select aria-label="Flex cooks" value={config.cooks} onChange={e => setConfig({ ...config, cooks: +e.target.value })}>{[1, 2, 3, 4].map(n => <option key={n}>{n}</option>)}</select></label><label>Incentive budget ($)<input aria-label="Flex budget" type="number" min="0" max="50" value={config.budget_cents / 100} onChange={e => setConfig({ ...config, budget_cents: Math.round(+e.target.value * 100) })} /></label><label>Quote life (seconds)<input aria-label="Quote lifetime" type="number" min="5" max="600" value={config.quote_ttl_seconds} onChange={e => setConfig({ ...config, quote_ttl_seconds: +e.target.value })} /></label><button className="rush-btn" disabled={locked} onClick={() => void startEpisode()}>Start new demo episode</button><small>Creates a new synthetic episode. Saved orders in previous episodes remain intact.</small></div></details></div>
    {error && <div className="rush-error" role="alert"><b>We couldn’t complete that step.</b> {error}</div>}
    {busy && !session && <div className="rush-loading" role="status">Loading the kitchen and checkout…</div>}
    {!session && !busy && <button className="rush-btn" onClick={() => void startEpisode(initialConfig)}>Start a new demo episode</button>}
    {session && <>
      {view === "shopper" ? <div className="flex-shopping">
        <div className="flex-shopping-main"><section className="flex-story"><span className="rush-eyebrow">GOOD FOOD. A TIME THAT WORKS FOR YOU.</span><h2>Give dinner a little room.</h2><p>Choose the earliest available pickup, or see if a later time comes with a saving. Your choice helps the kitchen plan the next orders.</p><div><span>✓ Your time, your choice</span><span>✓ Same meal</span><span>✓ Clear price before confirming</span></div></section>
          <section className="rush-panel flex-meal"><div className="flex-meal-art"><MealArt item={cart.item} /><span>HANABI / MADE FOR YOUR EVENING</span></div><div><span className="rush-eyebrow">YOUR MEAL</span><h2>{session.menu[cart.item]?.name}</h2><p>Prepared for your selected pickup time.</p><strong>{money(session.menu[cart.item]?.price || 0)}</strong><label>Choose a meal<select aria-label="Meal" value={cart.item} disabled={locked || !!receipt} onChange={e => updateCart({ ...cart, item: e.target.value })}>{Object.entries(session.menu).map(([id, m]) => <option key={id} value={id} disabled={m.available <= 0}>{m.name} · {money(m.price)}</option>)}</select></label></div></section>
          <section className="rush-panel flex-preferences"><span className="rush-eyebrow">WHAT WORKS FOR YOU?</span><h3>A deadline. A worthwhile saving.</h3><div><label>I need pickup by<select aria-label="Latest pickup" value={cart.latest_pickup_minute} disabled={locked || !!receipt} onChange={e => updateCart({ ...cart, latest_pickup_minute: +e.target.value })}>{[25, 35, 45, 55, 70, 90, 120].map(m => <option value={m} key={m}>{clock(m)}</option>)}</select></label><label>Waiting is worth at least<select aria-label="Minimum saving" value={cart.minimum_saving_cents} disabled={locked || !!receipt} onChange={e => updateCart({ ...cart, minimum_saving_cents: +e.target.value })}>{[100, 200, 300, 400].map(c => <option value={c} key={c}>{money(c)} off</option>)}</select></label></div><p>We use the limits you choose. You can always keep the regular option or leave without ordering.</p><div className="flex-find-actions"><button className="rush-btn" disabled={locked || !!receipt} onClick={() => void find(false)}>{busy ? "Checking availability…" : quote ? "Refresh pickup options" : "Find my pickup options"}</button><button className="rush-btn light" disabled={!agentAvailable || locked || !!receipt} onClick={() => void find(true)}><Icon name="ask" size={15} />{jobId ? "Gemini is checking…" : "Let Gemini find options"}</button></div></section>
          {job && <section className="rush-panel flex-agent-trace"><span className="rush-eyebrow">ACTUAL AGENT TOOL RESULTS</span><h3>{job.status === "done" ? "Checked choices. Your decision." : job.status === "running" ? "Investigating the available tradeoffs…" : "The agent did not complete"}</h3><div className="rush-tool-log">{(job.events || []).filter(e => e.kind === "tool").map((e, i) => <div key={i}><i /><span>{toolNames[e.tool || ""] || e.tool}{e.result?.status === "rejected" ? " · rejected" : ""}</span></div>)}</div>{job.result && <small>{job.result.model} · real model, simulated restaurant. Publishing choices does not book an order.</small>}</section>}
        </div>
        <aside className="flex-checkout rush-panel" aria-label="Pickup choices">
          {receipt ? <><span className="flex-confirm-icon">✓</span><span className="rush-eyebrow">CUSTOMER CHOICE CONFIRMED</span><h2>See you at {receipt.option.pickup_clock}.</h2><p>{session.menu[receipt.item]?.name}</p><div className="flex-confirm-price"><strong>{money(receipt.option.price_cents)}</strong>{receipt.option.discount_cents > 0 && <span>You save {money(receipt.option.discount_cents)}</span>}</div><div className="flex-receipt" data-testid="flex-receipt"><b>Production slots reserved</b><span>Cooking {clock(receipt.option.tasks[0].start)}–{clock(receipt.option.tasks[0].end)}</span><span>Packing {clock(receipt.option.tasks[1].start)}–{clock(receipt.option.tasks[1].end)}</span><small>{receipt.id} · simulated order · no charge</small></div><p className="flex-consent">You explicitly chose this time and price. Refreshing this page preserves your reservation.</p><button className="rush-btn" onClick={() => setView("merchant")}>See what changed in the kitchen ↗</button><button className="flex-text-button" onClick={() => { setReceipt(null); updateCart({ ...cart, cart_id: crypto.randomUUID() }); }}>Start another checkout</button></> : <><span className="rush-eyebrow">YOUR PICKUP, YOUR CALL</span><h2>{quote ? "Choose what suits you." : "Dinner on your terms."}</h2>{!quote && <div className="flex-empty"><div>◷</div><p>Check the kitchen for a regular pickup and any worthwhile later options.</p><small>Choices are based on current reservations and your preferences.</small></div>}{quote && <><div className={`flex-expiry ${expired ? "expired" : ""}`}>{expired ? "Availability changed or this quote expired. Refresh choices." : `Options valid for ${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`}</div><div className="flex-options" role="radiogroup" aria-label="Pickup time and price">{quote.options.map((o, i) => <button key={o.id} role="radio" aria-checked={selected === o.id} className={`flex-choice ${selected === o.id ? "selected" : ""} ${o.kind}`} disabled={locked || expired} onClick={() => setSelected(o.id)}><div><span>{o.kind === "regular" ? "Earliest available" : i === 1 ? "A little flexibility" : "More time, more saving"}</span><i>{selected === o.id ? "●" : "○"}</i></div><div><b>{o.pickup_clock}</b><strong>{money(o.price_cents)}</strong></div><p>{o.discount_cents ? `${money(o.discount_cents)} off · ${o.pickup_minute - quote.options[0].pickup_minute} minutes later` : "Regular price · no need to wait longer"}</p></button>)}</div>{quote.no_deal_reason && <p className="flex-no-deal" data-testid="flex-no-deal">{quote.no_deal_reason}. Regular pickup is still available.</p>}{chosen && <div className="flex-order-total"><span>Meal subtotal</span><strong>{money(chosen.price_cents)}</strong></div>}<button className="rush-btn flex-confirm" disabled={locked || expired || !chosen} onClick={() => void confirm()}>{busy ? "Reserving your choice…" : "Confirm this pickup"}</button><button className="flex-text-button" disabled={locked} onClick={() => void decline()}>Not now — leave without ordering</button><p className="flex-consent">Confirming means choosing this pickup time and price. These are proposals; availability, stock and the incentive budget are rechecked on confirmation.</p><small className="flex-source">{quote.source === "gemini" ? "Choices selected by real Gemini tools" : "Choices selected by the capacity planner"}</small></>}<div className="flex-checkout-footer">Demo checkout · USD before tax · no payment is taken.<br />No live DoorDash campaign or customer order is changed.</div></>}
        </aside>
      </div> : <>
        <section className="flex-merchant-intro"><div><span className="rush-eyebrow">SAME KITCHEN. A DIFFERENT RESERVATION.</span><h2>Make the flexibility real.</h2><p>A later pickup changes when the meal is cooked and packed. Existing work stays in its reserved slots.</p></div><a className="rush-btn light" href={`/flex?s=${session.id}&new=1`} target="_blank" rel="noreferrer">Open another customer checkout ↗</a></section>
        <div className="flex-merchant-stats"><div><span>Episode time</span><b>{session.clock}</b><small>Frozen synthetic service state</small></div><div><span>Existing orders protected</span><b>{pending}</b><small>Accepted reservations remain fixed</small></div><div><span>Incentive budget used</span><b>{money(session.spent_cents)} <em>/ {money(session.config.budget_cents)}</em></b><small>Spent only on confirmed choices</small></div><div><span>Confirmed new orders</span><b>{session.bookings.length}</b><small>Durable reservations, no real charges</small></div></div>
        {displayChoice && displayRegular ? <section className="rush-panel flex-proof" data-testid="flex-production-proof"><div className="rush-panel-head"><div><span className="rush-eyebrow">{evidenceReceipt ? "CONFIRMED CHOICE / QUOTE-TIME COMPARISON" : "PROPOSED CHOICE / NOT HELD"}</span><h3>{displayChoice.kind === "flexible" ? "The work moves with the pickup." : "Regular pickup keeps the earliest slot."}</h3></div><span className="rush-pill pale">{displayChoice.released_cook_minutes} near-term cook-minutes released</span></div><div className="flex-proof-grid"><div><span>Earliest option</span><b>{displayRegular.pickup_clock} · {money(displayRegular.price_cents)}</b><MiniPlan option={displayRegular} allocations={compareAlloc} end={timelineEnd} /><p>Cooking {clock(displayRegular.tasks[0].start)}–{clock(displayRegular.tasks[0].end)}; packing {clock(displayRegular.tasks[1].start)}–{clock(displayRegular.tasks[1].end)}.</p></div><div className="after"><span>{evidenceReceipt ? "Customer chose" : "Selected alternative"}</span><b>{displayChoice.pickup_clock} · {money(displayChoice.price_cents)}</b><MiniPlan option={displayChoice} allocations={compareAlloc} end={timelineEnd} /><p>Cooking {clock(displayChoice.tasks[0].start)}–{clock(displayChoice.tasks[0].end)}; packing {clock(displayChoice.tasks[1].start)}–{clock(displayChoice.tasks[1].end)}.</p></div></div><div className="flex-proof-notes"><span>✓ Existing reservations unchanged</span><span>✓ Cook and packing dependencies checked</span><span>✓ Ready at the chosen pickup; no modeled holding</span></div><p className="rush-footnote">Near-term window {session.clock}–{clock(session.peak_end)}. Capacity relief is planned work moved, not observed restaurant performance or conversion uplift.</p></section> : <section className="rush-panel flex-empty">Find pickup options in the customer view to compare production allocations.</section>}
        <div className="flex-owner-grid"><section className="rush-panel"><div className="rush-panel-head"><div><span className="rush-eyebrow">RESERVATION LEDGER</span><h3>What is actually committed?</h3></div><span className="rush-pill pale">Quotes reserve nothing until accepted</span></div><div className="rush-table-scroll"><table className="rush-results"><thead><tr><th>Order</th><th>Meal</th><th>Pickup</th><th>Price / saving</th><th>Cooking starts</th></tr></thead><tbody>{session.bookings.map(b => <tr key={b.id}><td>{b.id}<small>{b.source === "simulated_other_customer" ? "Explicit competing-customer demo event" : "Customer accepted"}</small></td><td>{session.menu[b.item]?.name}</td><td>{b.option.pickup_clock}</td><td>{money(b.option.price_cents)} / {money(b.option.discount_cents)}</td><td>{clock(b.option.tasks[0].start)}</td></tr>)}</tbody></table>{!session.bookings.length && <p className="flex-empty">No new orders have been accepted. Quoting has spent $0.</p>}</div></section><section className="rush-panel flex-race"><span className="rush-eyebrow">TRY THE CONFLICT CASE</span><h3>What if someone else gets the slot?</h3><p>Simulate another customer booking the currently selected proposal at full price. The original checkout must recheck availability before confirming.</p><button className="rush-btn light" disabled={locked || !quote || !!receipt || expired} onClick={() => void compete()}>Book this slot for another customer</button><small>This is an explicit synthetic incoming-order event, not an external customer or transaction.</small></section></div>
        <section className="rush-panel"><div className="rush-panel-head"><div><span className="rush-eyebrow">COMMITTED WORK ACROSS CHANNELS</span><h3>Existing promises stay visible.</h3></div><span className="rush-tiny">Some commitments in this stress episode are already at risk.</span></div><div className="flex-existing">{session.base_orders.filter(o => o.ready === null).map(o => <div key={o.id}><b>{o.id}</b><span>{o.channel === "doordash" ? "DoorDash" : o.channel === "ubereats" ? "Uber Eats" : "Pickup"}</span><span>{session.menu[o.item]?.name}</span><strong>Promised {clock(o.promise)}</strong></div>)}</div></section>
      </>}
      <details className="rush-assumptions flex-assumptions"><summary>How this demo works and what it proves</summary><p>The restaurant is a frozen synthetic episode at 17:42, shared with Rush Control's observation/reservation engine. New orders reserve future resources around the existing plan. Quote expiry uses real time. This does not simulate the rest of dinner, prove revenue uplift, or guarantee fulfillment through future disruptions. Readiness uses observed estimates plus an explicit allowance.</p><p>Gemini selects checked offers; code calculates times, price, stock, budget and capacity. Customer confirmation creates the reservation. Existing paid orders are not renegotiated. DoorDash-native feature absence is a working assumption; checkout/campaign access remains unverified.</p><pre>{JSON.stringify(session.assumptions, null, 2)}</pre></details>
    </>}
  </div>;
}

function MiniPlan({ option, allocations, end }: { option: FlexOption; allocations: FlexTask[]; end: number }) {
  const span = end - 12;
  const stations = [option.tasks[0].station, "packing"];
  return <div className="flex-mini-plan"><div className="flex-mini-axis"><span>{clock(12)}</span><span>{clock(end)}</span></div>{stations.map(s => <div className="flex-mini-row" key={s}><b>{stationNames[s]}</b><div><i className="flex-peak-zone" style={{ width: `${25 / span * 100}%` }} />{allocations.filter(t => t.station === s && t.end > 12 && t.start < end).map((t, i) => <span className="existing" key={`${t.task_id}-${i}`} style={{ left: `${Math.max(0, t.start - 12) / span * 100}%`, width: `${(Math.min(end, t.end) - Math.max(12, t.start)) / span * 100}%` }} title={`${t.order_id}: ${clock(t.start)}–${clock(t.end)}`} />)}{option.tasks.filter(t => t.station === s).map(t => <span className="chosen" key={t.task_id} style={{ left: `${(t.start - 12) / span * 100}%`, width: `${(t.end - t.start) / span * 100}%` }} title={`${clock(t.start)}–${clock(t.end)}`} />)}</div></div>)}<div className="flex-mini-legend"><span><i />Existing work</span><span><i />This meal</span><span>Shaded: near-term pressure</span></div></div>;
}
