import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { orderApi, OrderApiError, type Channel, type IncomingOrder, type Line, type OrderConfig, type OrderJob, type OrderSession, type PlanSet, type Priority } from "../api/orders";
import "../orders.css";

const channelNames: Record<Channel, string> = { doordash: "DoorDash", ubereats: "Uber Eats", dine_in: "Dine-in", pickup: "Pickup" };
const stationNames: Record<string, string> = { fryer: "Fryer", noodles: "Noodles", assembly: "Assembly", packing: "Finish / pack" };
const clock = (minute: number | null) => minute === null ? "—" : `${String(Math.floor((1050 + minute) / 60)).padStart(2, "0")}:${String((1050 + minute) % 60).padStart(2, "0")}`;
const eventLabels: Record<string, string> = { inspect_demand: "Inspected demand and kitchen load", compare_admission_plans: "Compared guarded admission plans", select_checked_plan: "Selected a checked plan" };

export default function OrderManager() {
  const [config, setConfig] = useState<OrderConfig | null>(null);
  const [session, setSession] = useState<OrderSession | null>(null);
  const [plans, setPlans] = useState<PlanSet | null>(null);
  const [priority, setPriority] = useState<Priority>("current");
  const [saved, setSaved] = useState<{ id: string; created: string }[]>([]);
  const [cooks, setCooks] = useState(3);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [jobId, setJobId] = useState<string | null>(null);
  const [job, setJob] = useState<OrderJob | null>(null);
  const current = useRef<OrderSession | null>(null);
  const mounted = useRef(true);
  const generation = useRef(0);

  async function show(next: OrderSession) {
    const gen = ++generation.current;
    current.current = next; setSession(next); setPlans(null);
    localStorage.setItem("gondola-order-session", next.id);
    const compared = await orderApi.plans(next.id);
    if (!mounted.current || gen !== generation.current) return;
    if (compared.revision !== next.revision) throw new Error("Kitchen state changed during comparison. Refresh the session.");
    setPlans(compared); setPriority(compared.recommended);
  }
  async function refresh() {
    if (current.current) await show(await orderApi.get(current.current.id));
  }
  useEffect(() => {
    mounted.current = true;
    void (async () => {
      try {
        const [cfg, sessions] = await Promise.all([orderApi.config(), orderApi.sessions()]);
        if (!mounted.current) return;
        setConfig(cfg); setSaved(sessions);
        const remembered = localStorage.getItem("gondola-order-session");
        const id = sessions.find(s => s.id === remembered)?.id;
        if (id) await show(await orderApi.get(id));
      } catch (e) { if (mounted.current) setError((e as Error).message); }
      finally { if (mounted.current) setBusy(false); }
    })();
    return () => { mounted.current = false; generation.current++; };
  }, []);
  async function act(work: () => Promise<void>) {
    setBusy(true); setError("");
    try { await work(); }
    catch (e) {
      setError((e as Error).message);
      if (e instanceof OrderApiError && e.status === 409) {
        try { await refresh(); } catch { /* Keep the original conflict visible. */ }
      }
    } finally { if (mounted.current) setBusy(false); }
  }
  async function start(demo: boolean) {
    await act(async () => { setJob(null); await show(await orderApi.create(cooks, demo)); setSaved(await orderApi.sessions()); });
  }
  useEffect(() => {
    if (!jobId) return;
    let stopped = false, polling = false;
    const poll = async () => {
      if (polling) return;
      polling = true;
      try {
        const result = await orderApi.job(jobId);
        if (stopped) return;
        setJob(result);
        if (result.status !== "running") {
          setJobId(null);
          await refresh();
          if (result.status !== "done") setError(`${result.error || "Model job did not complete"}. Session and local receipts refreshed.`);
        }
      } catch (e) { if (!stopped) { setError((e as Error).message); setJobId(null); } }
      finally { polling = false; }
    };
    void poll(); const timer = setInterval(poll, 900);
    return () => { stopped = true; clearInterval(timer); };
  }, [jobId]);

  const locked = busy || !!jobId;
  const selected = plans?.plans.find(p => p.strategy === priority);
  const active = (session?.counts.pending || 0) + (session?.counts.accepted || 0);
  const ready = !locked && !!selected?.allowed && !!active;

  return <div className="orders-workspace" data-testid="order-manager">
    <header className="orders-header"><div><span className="orders-eyebrow">GONDOLA / RUSH CONTROL / BACK HOUSE</span><h1>Order manager<span>.</span></h1><p>Accept the work the kitchen can deliver. Give every channel one capacity plan.</p></div><span className="orders-mode">Local simulation · no platform writes</span></header>
    <div className="orders-topbar"><label>New session cooks<select aria-label="New session cooks" value={cooks} disabled={locked} onChange={e => setCooks(+e.target.value)}>{[1, 2, 3, 4].map(c => <option key={c}>{c}</option>)}</select></label><button className="orders-btn" disabled={locked || !config} onClick={() => void start(true)}>Start 29-order burst</button><button className="orders-btn secondary" disabled={locked || !config} onClick={() => void start(false)}>Empty session</button>{saved.length > 0 && <label>Resume<select aria-label="Resume service session" value={session?.id || ""} disabled={locked} onChange={e => { if (e.target.value) void act(async () => { setJob(null); await show(await orderApi.get(e.target.value)); }); }}><option value="">Choose a saved session</option>{saved.map(s => <option key={s.id} value={s.id}>{s.id.slice(0, 8)} · {new Date(s.created).toLocaleTimeString()}</option>)}</select></label>}<Link to="/rush">Capacity replay →</Link></div>
    {error && <div className="orders-error" role="alert">{error}<button disabled={locked} onClick={() => void act(refresh)}>Refresh</button></div>}
    {busy && <p className="orders-loading" role="status">Checking kitchen commitments…</p>}
    {!session && !busy && <section className="orders-welcome"><span className="orders-eyebrow">ONE ORDER MANAGER, CHECKED TOOLS</span><h2>29 orders. One kitchen.</h2><div className="orders-channels">{Object.entries(channelNames).map(([key, label], i) => <div key={key}><strong>{[12, 8, 5, 4][i]}</strong><span>{label}</span></div>)}</div><p>Run the synthetic burst or start an empty session. Five dine-in orders are already confirmed; new delivery and pickup requests need a capacity check.</p><p>One agent can inspect, compare and select. Scheduling, inventory and admission limits stay in code.</p></section>}
    {session && <>
      <div className="orders-summary"><div><span>Kitchen clock</span><strong>{clock(session.minute)}</strong><small>Simulated service · {session.policy.cooks} cooks</small></div><div><span>Awaiting decision</span><strong>{session.counts.pending}</strong><small>{session.policy.response_minutes}-minute response window</small></div><div><span>Committed / complete</span><strong>{session.counts.accepted + session.counts.completed}<em> / {session.orders.length}</em></strong><small>{session.orders.filter(o => o.decision === "accept_later").length} accepted with a later ready time</small></div><div className={session.at_risk ? "risk" : ""}><span>Promises at risk</span><strong>{session.at_risk}</strong><small>{session.counts.declined} declined · {session.counts.expired} expired</small></div></div>
      <div className="orders-channel-counts">{Object.entries(channelNames).map(([key, label]) => <span key={key}>{label} <b>{session.orders.filter(o => o.channel === key).length}</b></span>)}</div>
      {session.at_risk > 0 && <div className="orders-warning"><b>{session.at_risk} existing commitments exceed current capacity estimates.</b> Their original promises remain fixed. New plans must protect them.</div>}
      {Object.keys(session.stock_shortfalls).length > 0 && <div className="orders-warning">Confirmed work exceeds recorded stock: {Object.entries(session.stock_shortfalls).map(([item, quantity]) => `${quantity} × ${config?.menu[item]?.name || item}`).join(", ")}. Imported commitments were preserved.</div>}
      <div className="orders-grid"><section className="orders-panel"><div className="orders-panel-head"><div><span className="orders-eyebrow">SHARED COOKS, STATIONS & FINISHING</span><h2>Capacity before commitment</h2></div><b>{Math.round(session.shared_cook_utilization * 100)}% cooks reserved</b></div><div className="orders-stations">{session.stations.map(s => <div key={s.id} className={s.load >= .9 ? "hot" : ""}><span>{stationNames[s.id]}</span><strong>{Math.round(s.load * 100)}%</strong><div className="orders-meter"><i style={{ width: `${Math.min(100, s.load * 100)}%` }} /></div><small>{s.blocked_until > session.minute ? `Unavailable until ${clock(s.blocked_until)}` : s.speed !== 1 ? `${s.speed}× work rate` : "Declared normal rate"}</small></div>)}</div><p className="orders-note">Reservations over the next 15 minutes. Quantities consume cooking capacity; each complete order then uses the shared finishing slot.</p><div className="orders-controls"><button disabled={locked} onClick={() => void act(async () => { await show((await orderApi.capacity(session, .5)).session); })}>Simulate slow fryer</button><button disabled={locked} onClick={() => void act(async () => { await show((await orderApi.capacity(session, 1)).session); })}>Restore fryer</button><span>Advance simulation</span>{[1, 5, 15].map(delta => <button key={delta} disabled={locked || session.minute + delta > 240} onClick={() => void act(async () => { await show((await orderApi.advance(session, session.minute + delta)).session); })}>+{delta} min</button>)}</div>{session.counts.pending > 0 && <p className="orders-note">Unanswered requests expire if you advance past their response deadline. A later ready time does not postpone acceptance.</p>}
        <div className="orders-next"><h3>Next kitchen work</h3>{[...session.plan].sort((a, b) => a.start - b.start).slice(0, 6).map(t => <div key={t.task_id}><b>{clock(t.start)}</b><span>{t.order_id.split(":")[1]}</span><small>{stationNames[t.station]} · {t.frozen ? "already in progress" : `reserved through ${clock(t.end)}`}</small></div>)}{!session.plan.length && <p className="orders-note">No committed kitchen work.</p>}</div>
      </section><section className="orders-panel orders-agent"><span className="orders-eyebrow">ONE ORDER MANAGER</span><h2>Check the whole batch.</h2><p>Keep accepted promises protected. Admit new orders at the requested time or within an explicitly authorized later window.</p><div className="orders-plans" aria-label="Checked admission plans">{plans?.plans.map(p => <label key={p.strategy} className={`${priority === p.strategy ? "selected" : ""} ${p.allowed ? "" : "blocked"}`}><input type="radio" name="admission-priority" checked={priority === p.strategy} disabled={locked || !p.allowed} onChange={() => setPriority(p.strategy)} /><div><b>{p.label}</b><span>{p.allowed ? p.actions.length ? `${p.accepted_now} at requested time · ${p.accepted_later} later · ${p.declined} declined` : p.next_work.length ? `Next: ${p.next_work[0].order_id.split(":")[1]} at ${clock(p.next_work[0].start)} · ${p.existing_late_minutes} estimated late minutes` : "No new requests or unstarted work" : `Blocked: would worsen ${p.worsened_orders.join(", ")}`}</span></div></label>)}</div>{!plans && <p className="orders-note">Loading checked plans…</p>}<button className="orders-btn" disabled={!ready || !config?.agent_configured} onClick={() => void act(async () => { setJob(null); setJobId((await orderApi.agent(session)).id); })}>{jobId ? "Order Manager working…" : "Ask Order Manager to decide"}</button><small className="orders-note">{config?.agent_configured ? "Model configured. It selects a compared plan; the workflow rechecks and commits locally." : "Model unavailable. The checked rules path remains usable."}</small><button className="orders-btn secondary" disabled={!ready} onClick={() => void act(async () => { if (selected) { setJob(null); await show((await orderApi.apply(session, selected)).session); } })}>Apply checked plan · rules</button>{job && <div className="orders-trace">{job.events.filter(e => e.kind === "tool").map((e, i) => <div key={i}>{eventLabels[e.tool || ""] || e.tool}{e.result?.status === "rejected" ? " · rejected" : ""}</div>)}{job.result?.local_receipt_verified && <b data-testid="order-agent-receipt">✓ Local admission receipt verified · {job.result.model}</b>}</div>}<p className="orders-note">A declined request stays in the record. Existing confirmed orders are never silently rejected to improve a score.</p></section></div>
      <section className="orders-panel"><div className="orders-panel-head"><div><span className="orders-eyebrow">FOUR CHANNELS, ONE COMMITTED QUEUE</span><h2>Every request stays visible</h2></div><button className="orders-btn secondary" disabled={locked} onClick={() => void act(refresh)}>Refresh state</button></div><div className="orders-table-wrap"><table><thead><tr><th>Order / portions</th><th>Channel</th><th>Decision</th><th>Requested</th><th>Promised</th><th>Estimated ready</th><th>Evidence</th></tr></thead><tbody>{session.orders.map(o => <tr key={o.key} className={o.at_risk ? "at-risk" : ""}><td><b>{o.order_id}</b><small>{o.items.map(l => `${l.quantity} × ${config?.menu[l.item]?.name || l.item}`).join(", ")}</small></td><td>{channelNames[o.channel]}</td><td><span className={`orders-status ${o.status}`}>{o.status === "pending" ? "Awaiting decision" : o.status === "completed" ? "Completed" : o.decision === "accept_later" ? "Accepted later" : o.status === "accepted" ? "Committed" : o.status}</span>{o.status === "pending" && <small>Reply by {clock(o.response_deadline)}</small>}</td><td>{clock(o.requested_ready_minute)}</td><td>{clock(o.promise)}</td><td>{clock(o.predicted_ready)}{o.at_risk && <small>Promise at risk</small>}</td><td className="orders-evidence">{o.reason}</td></tr>)}</tbody></table>{!session.orders.length && <p className="orders-note">Add a request below to start planning.</p>}</div></section>
      <IntakeForm key={session.id} config={config} session={session} locked={locked} submit={orders => act(async () => { await show((await orderApi.intake(session, orders)).session); })} />
      {session.receipts.length > 0 && <details className="orders-panel orders-receipts"><summary>Local action receipts ({session.receipts.length} shown)</summary>{[...session.receipts].reverse().map(r => <div key={r.receipt_id}><b>{r.action === "admission_plan" ? "Admission plan confirmed locally" : r.action.replace(/_/g, " ")}</b><span>{clock(r.minute)} · {r.decision_mode === "model_selected" ? "Model-selected checked plan" : "Rules / local command"}{r.decisions && ` · ${r.decisions.length} requests decided`}</span><small>{r.receipt_id} · no external verification</small></div>)}</details>}
      <footer className="orders-note">Synthetic menu estimates and simulated task progress. This workflow does not connect to DoorDash, Uber Eats or a live KDS. Original close and forecasting tools remain available separately.</footer>
    </>}
  </div>;
}

function IntakeForm({ config, session, locked, submit }: { config: OrderConfig | null; session: OrderSession; locked: boolean; submit: (orders: IncomingOrder[]) => Promise<void> }) {
  const [channel, setChannel] = useState<Channel>("doordash");
  const [id, setId] = useState("");
  const [lead, setLead] = useState(15);
  const [later, setLater] = useState(false);
  const [latest, setLatest] = useState(45);
  const [confirmed, setConfirmed] = useState(false);
  const [lines, setLines] = useState<Line[]>([{ item: "tonkotsu", quantity: 1 }]);
  const keys = Object.keys(config?.menu || {});
  return <details className="orders-panel orders-intake"><summary>Add a normalized order</summary><form onSubmit={e => { e.preventDefault(); void submit([{ order_id: id || `ORDER-${Date.now().toString(36)}`, channel, received_minute: session.minute, requested_ready_minute: session.minute + lead, latest_ready_minute: session.minute + (later && !confirmed ? latest : lead), commitment: confirmed ? "confirmed" : "request", items: lines }]); }}><div className="orders-form-row"><label>Channel<select aria-label="Incoming channel" value={channel} onChange={e => setChannel(e.target.value as Channel)}>{Object.entries(channelNames).map(([key, name]) => <option key={key} value={key}>{name}</option>)}</select></label><label>Order ID<input aria-label="Incoming order ID" placeholder="Generated if empty" value={id} pattern="[A-Za-z0-9_-]+" maxLength={80} onChange={e => setId(e.target.value)} /></label><label>Requested in (min)<input aria-label="Requested lead minutes" type="number" min="1" max="120" value={lead} onChange={e => setLead(+e.target.value)} required /></label></div>{lines.map((line, i) => <div className="orders-form-row" key={i}><label>Menu item<select aria-label={`Order item ${i + 1}`} value={line.item} onChange={e => setLines(lines.map((l, j) => j === i ? { ...l, item: e.target.value } : l))}>{keys.filter(k => k === line.item || !lines.some(l => l.item === k)).map(k => <option key={k} value={k}>{config?.menu[k].name}</option>)}</select></label><label>Portions<input aria-label={`Order quantity ${i + 1}`} type="number" min="1" max="10" value={line.quantity} onChange={e => setLines(lines.map((l, j) => j === i ? { ...l, quantity: +e.target.value } : l))} required /></label>{i > 0 && <button type="button" onClick={() => setLines(lines.filter((_, j) => i !== j))}>Remove line</button>}</div>)}<button type="button" disabled={lines.length >= keys.length} onClick={() => setLines([...lines, { item: keys.find(k => !lines.some(l => l.item === k))!, quantity: 1 }])}>Add menu line</button><label className="orders-check"><input type="checkbox" checked={confirmed} onChange={e => setConfirmed(e.target.checked)} />Already confirmed upstream — preserve its original promise</label>{!confirmed && <label className="orders-check"><input type="checkbox" checked={later} onChange={e => setLater(e.target.checked)} />A later ready time is explicitly authorized</label>}{later && !confirmed && <label>Latest authorized ready in (min)<input aria-label="Latest authorized lead minutes" type="number" min={lead} max="120" value={latest} onChange={e => setLatest(+e.target.value)} required /></label>}<button className="orders-btn" disabled={locked}>Add to observed inbox</button></form></details>;
}
