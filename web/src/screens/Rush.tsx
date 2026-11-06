import { useEffect, useRef, useState } from "react";
import { defaultRequest, rushApi, type Comparison, type Frame, type ModelJob, type Reservation, type RushConfig, type RushRequest, type RushRun } from "../api/rush";
import { Icon } from "../components/ui";
import "../rush.css";

const stationName: Record<string, string> = { fryer: "Fryer", noodles: "Noodles", assembly: "Assembly", packing: "Packing" };
const channelName: Record<string, string> = { doordash: "DoorDash", ubereats: "Uber Eats", pickup: "Pickup" };
const modeNames: Record<string, string> = { fifo: "FIFO", deadline: "Earliest promise", slack: "Remaining slack", independent: "Separate campaigns", coordinated: "Connected control" };
const money = (c: number) => `$${(c / 100).toFixed(2)}`;
const time = (m: number) => `${String(Math.floor((1050 + m) / 60)).padStart(2, "0")}:${String((1050 + m) % 60).padStart(2, "0")}`;
const labels: Record<string, string> = { inspect_kitchen: "Read accepted orders, resources and inventory", compare_approved_offers: "Checked approved offers against shared reservations", check_offer: "Checked an alternative intervention", publish_simulated_offer: "Applied a checked offer to the simulated menu", pause_simulated_offers: "Paused offers to protect capacity", training_brief: "Read development cases and baseline results", test_policy: "Tested a candidate policy", submit_policy: "Submitted a tested policy for independent evaluation" };

function Bowl({ fried = false }: { fried?: boolean }) {
  return <svg viewBox="0 0 180 110" aria-hidden="true" className="rush-bowl"><ellipse cx="90" cy="88" rx="67" ry="9" fill="#183f2e12" /><path d="M26 43h128c-4 31-26 45-64 45S31 74 26 43" fill={fried ? "#d69652" : "#dce8cf"} /><ellipse cx="90" cy="43" rx="64" ry="21" fill="#fbf3d7" /><ellipse cx="90" cy="43" rx="55" ry="15" fill={fried ? "#b76d34" : "#b4c96f"} /><path d="M53 36q13-17 26 0t26 0t26 0M47 48q13-17 26 0t26 0t26 0" fill="none" stroke="#f6e4af" strokeWidth="5" strokeLinecap="round" /><ellipse cx="103" cy="38" rx="21" ry="11" transform="rotate(-15 103 38)" fill="#b47b5f" /><ellipse cx="106" cy="37" rx="12" ry="6" transform="rotate(-15 106 37)" fill="#d09b7a" /><circle cx="67" cy="43" r="7" fill="#59864e" /><circle cx="76" cy="31" r="5" fill="#59864e" /><path d="M82 11q-6-7 0-12M98 13q-6-7 0-12" stroke="#9cae9a" fill="none" strokeWidth="2" strokeLinecap="round" /></svg>;
}

export default function Rush() {
  const [config, setConfig] = useState<RushConfig | null>(null);
  const [req, setReq] = useState<RushRequest>(defaultRequest);
  const [data, setData] = useState<Comparison | null>(null);
  const [mode, setMode] = useState("coordinated");
  const [minute, setMinute] = useState(12);
  const [playing, setPlaying] = useState(false);
  const [busy, setBusy] = useState(true);
  const [error, setError] = useState("");
  const [job, setJob] = useState<ModelJob | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);
  const [tab, setTab] = useState("service");
  const [selected, setSelected] = useState<string | null>(null);
  const [history, setHistory] = useState<{ id: string; kind: string; status: string; created: string }[]>([]);
  const generation = useRef(0);
  const reqRef = useRef(req);
  const lastLab = useRef<ModelJob | null>(null);

  async function load(next: RushRequest, keepMinute = 12) {
    const gen = ++generation.current;
    setBusy(true); setError(""); setPlaying(false); setSelected(null); setJob(null);
    setReq(next); reqRef.current = next;
    try {
      const result = await rushApi.compare(next);
      if (gen !== generation.current) return;
      setData(result); setMinute(keepMinute);
    } catch (e) { if (gen === generation.current) setError((e as Error).message); }
    finally { if (gen === generation.current) setBusy(false); }
  }
  useEffect(() => {
    let mounted = true;
    rushApi.config().then(c => {
      if (!mounted) return;
      setConfig(c);
      const pressure = c.forecast ? Math.min(2, Math.max(0.25, c.forecast.p90 / c.forecast.p50)) : 1;
      void load({ ...defaultRequest, forecast_pressure: Number(pressure.toFixed(2)) });
    }).catch(e => { if (mounted) { setError(e.message); setBusy(false); } });
    rushApi.history().then(h => mounted && setHistory(h)).catch(() => {});
    return () => { mounted = false; generation.current++; };
  }, []);
  useEffect(() => {
    if (!playing) return;
    const id = setInterval(() => setMinute(m => { if (m >= 80) { setPlaying(false); return m; } return m + 1; }), 420);
    return () => clearInterval(id);
  }, [playing]);
  useEffect(() => {
    if (!jobId) return;
    let stopped = false;
    const poll = async () => {
      try {
        const j = await rushApi.job(jobId);
        if (stopped) return;
        setJob(j);
        if (j.status !== "running") {
          setJobId(null);
          if (j.status === "failed" || j.status === "interrupted") setError(j.error || "The request did not complete. No successful AI action is claimed.");
          if (j.result?.comparison) { setData(j.result.comparison); setReq(j.result.comparison.request); reqRef.current = j.result.comparison.request; setMode("coordinated"); }
          if (j.kind === "policy_lab" && j.status === "done") lastLab.current = j;
          rushApi.history().then(setHistory).catch(() => {});
        }
      } catch (e) { if (!stopped) { setError((e as Error).message); setJobId(null); } }
    };
    void poll(); const id = setInterval(poll, 900);
    return () => { stopped = true; clearInterval(id); };
  }, [jobId]);

  const run = data?.runs[mode];
  const frame = run?.frames[Math.min(minute, run.frames.length - 1)];
  const menu = config?.menu || {};
  const pending = frame?.orders.filter(o => o.ready === null) || [];
  const atRisk = pending.filter(o => (o.predicted_ready ?? 0) > o.promise).length;
  const offerItem = frame?.offer ? menu[frame.offer.item] : null;
  const connected = data?.runs.coordinated.metrics;
  const separate = data?.runs.independent.metrics;
  const lab = job?.kind === "policy_lab" ? job : lastLab.current;
  const qualification = lab?.result?.qualification;
  const receipt = job?.kind === "controller" && job.status === "done" ? job.result?.receipt : null;
  const onIncident = (kind: string) => void load({ ...req, incident: kind, incident_at: Math.max(4, Math.min(minute, 35)) }, Math.max(4, Math.min(minute, 35)));
  async function startAgent() {
    setError(""); setPlaying(false); setJob(null);
    try { const r = await rushApi.agent({ ...reqRef.current, minute: Math.max(10, Math.min(minute, 38)) }); setMinute(Math.max(10, Math.min(minute, 38))); setJobId(r.id); }
    catch (e) { setError((e as Error).message); }
  }
  async function startLab() {
    setError(""); setJob(null);
    try { const r = await rushApi.lab(); setJobId(r.id); }
    catch (e) { setError((e as Error).message); }
  }

  return <div className="rush" data-testid="rush-workspace">
    <header className="rush-head">
      <div><div className="rush-eyebrow">HANABI RAMEN / OPERATIONS</div><h1>Rush control<span>.</span></h1></div>
      <div className="rush-source"><span className="rush-pill">Simulated restaurant & campaigns</span><span className="rush-model"><i />{config?.agent_configured ? "Gemini available" : "Offline controller"}</span></div>
    </header>
    <section className="rush-intro">
      <div><span className="rush-eyebrow">ONE PLAN, FROM DEMAND TO PICKUP</span><h2>Sell what the kitchen<br />can deliver.</h2><p>Protect accepted orders. Put spare capacity to work. Adapt when service changes.</p></div>
      <div className="rush-intro-facts"><div><strong>{req.scenario === "overload" ? 42 : req.scenario === "quiet" ? 10 : 27}</strong><span>initial commitments</span></div><div><strong>3</strong><span>ordering channels</span></div><div><strong>{req.cooks}</strong><span>shared cooks</span></div></div>
    </section>
    <div className="rush-toolbar">
      <div className="rush-tabs" aria-label="Workspace"><button className={tab === "service" ? "on" : ""} onClick={() => setTab("service")}>Service desk</button><button className={tab === "lab" ? "on" : ""} onClick={() => setTab("lab")}>Strategy lab <span>AI</span></button></div>
      <label>Scenario<select aria-label="Rush scenario" value={req.scenario} disabled={busy || !!jobId} onChange={e => void load({ ...req, scenario: e.target.value })}>{(config?.scenarios || [{ id: "rush", name: "Event-night rush" }]).map(s => <option key={s.id} value={s.id}>{s.name}</option>)}</select></label>
      <label>Cooks<select aria-label="Shared cooks" value={req.cooks} disabled={busy || !!jobId} onChange={e => void load({ ...req, cooks: +e.target.value })}>{[1, 2, 3, 4].map(n => <option key={n}>{n}</option>)}</select></label>
      <details className="rush-settings"><summary>Scenario settings</summary><div><label>Random seed<input aria-label="Scenario seed" type="number" min="0" max="1000000" value={req.seed} onChange={e => setReq({ ...req, seed: +e.target.value })} /></label><label>Offer budget ($)<input aria-label="Offer budget" type="number" min="0" max="50" value={req.budget_cents / 100} onChange={e => setReq({ ...req, budget_cents: Math.round(+e.target.value * 100) })} /></label><label>Forecast reserve multiplier<input aria-label="Forecast reserve multiplier" type="number" min="0.25" max="2" step="0.05" value={req.forecast_pressure} onChange={e => setReq({ ...req, forecast_pressure: +e.target.value })} /></label><button className="rush-btn" disabled={busy || !!jobId} onClick={() => void load(req)}>Apply settings</button></div></details>
    </div>
    {error && <div className="rush-error" role="alert"><b>Couldn’t complete that request.</b> {error} <button onClick={() => void load(req)}>Retry comparison</button></div>}
    {busy && <div className="rush-loading" role="status"><span />Replaying the same service across five controllers…</div>}
    {data && frame && run && !busy && <>
      {tab === "service" ? <>
        <section className="rush-replay">
          <button className="rush-play" aria-label={playing ? "Pause service replay" : "Play service replay"} onClick={() => { if (minute >= 80) setMinute(0); setPlaying(!playing); }}>{playing ? "Ⅱ" : "▶"}</button>
          <div className="rush-time"><strong>{time(minute)}</strong><span>Service replay</span></div>
          <input aria-label="Service minute" type="range" min="0" max="80" value={minute} onChange={e => { setPlaying(false); setMinute(+e.target.value); }} />
          <span className="rush-tiny">{time(0)}–{time(80)}</span>
          <button className="rush-btn light" disabled={!!jobId} onClick={() => onIncident("fryer_slowdown")}>Slow the fryer</button>
          <button className="rush-btn light" disabled={!!jobId} onClick={() => onIncident("courier_delay")}>Delay Dashers</button>
          <button className="rush-icon" aria-label="Remove disruption" title="Remove disruption" disabled={!!jobId} onClick={() => onIncident("none")}>↺</button>
        </section>
        <div className="rush-modebar"><span>Viewing</span>{["fifo", "deadline", "slack", "independent", "coordinated"].map(m => <button key={m} className={mode === m ? "on" : ""} onClick={() => setMode(m)}>{modeNames[m]}</button>)}</div>
        <div className="rush-grid">
          <div className="rush-maincol">
            <section className="rush-panel"><div className="rush-panel-head"><div><span className="rush-eyebrow">SHARED CAPACITY</span><h3>The kitchen, right now</h3></div><span className="rush-pill pale">{pending.length} orders in progress</span></div>
              <div className="rush-stations">{frame.stations.map(s => <div key={s.id} className={`rush-station ${s.load >= 0.9 || s.blocked ? "hot" : ""}`}><div><span>{stationName[s.id]}</span><b>{Math.round(s.load * 100)}<small>%</small></b></div><div className="rush-meter"><i style={{ width: `${Math.min(100, s.load * 100)}%` }} /></div><p>{s.blocked ? "Temporarily unavailable" : s.speed < 1 ? "Half speed · capacity reduced" : s.active.length ? `Working on ${s.active.join(", ")}` : "Free to start work"}</p></div>)}</div>
              <p className="rush-footnote">Reserved minutes over the next 15 minutes. Cooking stations share {req.cooks} cooks; packing has its own slot.</p>
              {frame.events.length > 0 && <div className="rush-event" role="status"><span>↳</span><div><b>{time(frame.events[frame.events.length - 1].minute)} · Conditions changed</b><p>{frame.events[frame.events.length - 1].text}</p></div></div>}
              <Timeline run={run} frame={frame} minute={minute} select={setSelected} />
              <div className="rush-offer-checks"><span className="rush-eyebrow">WHAT CAN WE SAFELY FEATURE?</span>{frame.offer_checks?.map(c => <div key={c.item} className={c.allowed ? "allowed" : "blocked"}><b>{c.allowed ? "✓" : "−"}</b><div><strong>{c.name}</strong><span>{c.allowed ? `Estimated ready ${time(c.predicted_ready_minute)} · within the reserve` : c.reason}</span></div><small>{Math.round(c.station_load * 100)}% {stationName[c.station]?.toLowerCase()}</small></div>)}</div>
              {atRisk > 0 && <div className="rush-risk"><b>{atRisk} accepted promises at risk</b><span>Current estimates exceed their original pickup times. These remain in every metric.</span></div>}
            </section>
            <section className="rush-panel"><div className="rush-panel-head"><div><span className="rush-eyebrow">ALL CHANNELS, ONE QUEUE</span><h3>Committed work</h3></div><span className="rush-tiny">Promises stay fixed when ETAs change</span></div>
              <div className="rush-ticket-wrap"><table className="rush-tickets"><thead><tr><th>Order / item</th><th>Channel</th><th>Promised</th><th>Courier ETA</th><th>State</th></tr></thead><tbody>{[...frame.orders].sort((a, b) => a.promise - b.promise).map(o => <tr key={o.id} className={selected === o.id ? "selected" : ""} onClick={() => setSelected(o.id)}><td><b>{o.id}</b><span>{menu[o.item]?.name || o.item}</span></td><td><span className={`rush-channel ${o.channel}`}>{channelName[o.channel]}</span></td><td>{time(o.promise)}</td><td>{o.eta === null ? "Customer pickup" : time(o.eta)}</td><td><span className={`rush-state ${o.state}`}>{o.state}</span></td></tr>)}</tbody></table>{frame.orders.length === 0 && <div className="rush-empty">Orders will arrive as the replay advances.</div>}</div>
            </section>
          </div>
          <aside className="rush-aside">
            <section className="rush-offer"><div className="rush-panel-head"><div><span className="rush-eyebrow">FIRST-PARTY MENU PREVIEW</span><h3>{offerItem ? "Spare capacity, put to work." : "Protect the queue first."}</h3></div><span className="rush-pill pale">Simulated</span></div><div className="rush-offer-art"><Bowl fried={frame.offer?.item === "karaage" || frame.offer?.item === "gyoza"} /></div><h4>{offerItem?.name || "No active offer"}</h4><p>{offerItem && frame.offer ? `${money(offerItem.price - frame.offer.discount_cents)} · ${frame.offer.discount_cents ? money(frame.offer.discount_cents) + " off" : "Featured without discount"}` : "Offers stay paused when the current model cannot reserve safe capacity."}</p><div className="rush-offer-note">{offerItem ? `Uses ${stationName[offerItem.station].toLowerCase()} capacity. Rechecked against stock, shared cooks and existing promises.` : "A no-offer decision is a valid outcome."}</div><div className="rush-budget"><span>Campaign spend</span><b>{money(frame.spent_cents)} <small>/ {money(req.budget_cents)}</small></b></div><div className="rush-meter"><i style={{ width: `${req.budget_cents ? Math.min(100, frame.spent_cents / req.budget_cents * 100) : 0}%` }} /></div></section>
            <section className="rush-panel rush-agent"><span className="rush-eyebrow">TOOL-USING AGENT</span><h3>Let Gondola make the call.</h3><p>Gemini inspects the observed kitchen, checks alternatives, and applies one guarded intervention to this simulated menu.</p><button className="rush-btn" disabled={!config?.agent_configured || !!jobId} onClick={() => void startAgent()}><Icon name="ask" size={17} />{jobId ? "Agent working…" : "Ask the agent to act"}</button><span className="rush-tiny">Uses your configured model. No live campaign is changed.</span>
              {receipt && <div className="rush-receipt" data-testid="agent-receipt"><b>✓ Simulated action confirmed</b><p>{receipt.action === "feature_item" ? `Featured ${menu[receipt.item || ""]?.name || receipt.item} at ${time(receipt.minute)}.` : `Paused offers at ${time(receipt.minute)}.`}</p><small>Receipt {receipt.receipt_id} · {job?.result?.model}</small></div>}
              {job?.kind === "controller" && <div className="rush-tool-log">{job.events.filter(e => e.kind === "tool").map((e, i) => <div key={i}><i /><span>{labels[e.tool || ""] || e.tool}{e.result?.status === "rejected" ? " · rejected" : ""}</span></div>)}{jobId && <div><i className="pulse" /><span>Waiting for the next model/tool result</span></div>}</div>}
            </section>
            <section className="rush-panel rush-learning"><span className="rush-eyebrow">LEARN FROM COMPLETED WORK</span><h3>Estimates that update.</h3><p>Only observed task completions update preparation estimates.</p>{frame.learning.length ? frame.learning.slice(-2).map((l, i) => <div key={`${l.minute}-${i}`}><b>{menu[l.item]?.name}</b><span>{l.estimated_work.toFixed(1)} → {l.updated_estimate.toFixed(1)} work-minutes <small>after completion at {time(l.minute)}</small></span></div>) : <span className="rush-tiny">Waiting for the first completed cooking task.</span>}</section>
            {config?.forecast && <section className="rush-forecast"><span className="rush-eyebrow">FORECAST CONTEXT</span><strong>{Math.round(config.forecast.p50)} orders</strong><p>Existing synthetic-store forecast · range {Math.round(config.forecast.p10)}–{Math.round(config.forecast.p90)}.</p><small>Its uncertainty sets a ×{req.forecast_pressure.toFixed(2)} lead-time reserve. No live weather or event feed.</small></section>}
          </aside>
        </div>
      </> : <section className="rush-panel rush-lab"><div className="rush-panel-head"><div><span className="rush-eyebrow">DEVELOP → TEST → INDEPENDENTLY CHECK</span><h2>A policy has to earn its place.</h2><p>Gemini proposes bounded offer policies, runs real development simulations, learns from the results, and submits a tested candidate.</p></div><button className="rush-btn" disabled={!!jobId || !config?.agent_configured} onClick={() => void startLab()}>{jobId ? "Experiment running…" : "Run the strategy lab"}</button></div><div className="rush-lab-rules"><span>3 development cases</span><span>Up to 6 candidate tests</span><span>6 unseen evaluation cases</span><span>6-policy conventional search</span></div><p className="rush-footnote">The agent cannot edit the evaluator or read unseen outcomes. These are parameterized policies, not arbitrary code generation. A failed candidate leaves the default in place.</p>
        {lab?.events && <div className="rush-lab-progress">{lab.events.filter(e => e.kind === "tool" || e.kind === "evaluation").map((e, i) => <div key={i}><span>{String(i + 1).padStart(2, "0")}</span><b>{e.kind === "evaluation" ? "Agent stopped · independent evaluation" : labels[e.tool || ""] || e.tool}</b>{e.tool === "test_policy" && e.result?.policy && <small>{e.result.policy.name} · score {e.result.mean_score}</small>}</div>)}</div>}
        {lab?.result?.trials && <table className="rush-results"><thead><tr><th>Agent candidate</th><th>Development score</th><th>Existing orders on time</th></tr></thead><tbody>{lab.result.trials.map((t, i) => <tr key={i}><td>{t.policy.name}</td><td>{t.mean_score.toFixed(2)}</td><td>{t.mean_existing_on_time.toFixed(1)}</td></tr>)}</tbody></table>}
        {qualification && <div className={`rush-qualification ${qualification.qualified ? "passed" : ""}`} data-testid="lab-result"><div><span className="rush-eyebrow">INDEPENDENT RESULT</span><h3>{qualification.qualified ? "Candidate qualified in the modeled cases." : "The default stays in place."}</h3><p>{qualification.explanation}</p></div><div className="rush-lab-scores"><div><span>Default</span><b>{qualification.default.mean_score.toFixed(2)}</b></div><div><span>Conventional search</span><b>{qualification.conventional_search.mean_score.toFixed(2)}</b></div><div><span>Agent candidate</span><b>{qualification.candidate.mean_score.toFixed(2)}</b></div></div>{qualification.qualified && <button className="rush-btn" disabled={busy} onClick={() => { void load({ ...req, policy: qualification.selected_policy }); setTab("service"); }}>Use the qualified policy</button>}<small>Fixed score uses modeled contribution and declared lateness/holding penalties. This is not a restaurant pilot or measured conversion uplift.</small></div>}
        {history.length > 0 && <details className="rush-history"><summary>Saved local runs and receipts ({history.length})</summary>{history.map(h => <button key={h.id} onClick={() => { if (h.kind === "comparison") return; rushApi.job(h.id).then(j => { setJob(j); if (j.kind === "policy_lab") lastLab.current = j; if (j.result?.comparison) { setData(j.result.comparison); setReq(j.result.comparison.request); reqRef.current = j.result.comparison.request; setMode("coordinated"); } }).catch(e => setError(e.message)); }}>{h.kind.replace(/_/g, " ")} · {h.status} <span>{new Date(h.created).toLocaleTimeString()}</span></button>)}</details>}
      </section>}
      <section className="rush-panel rush-comparison"><div className="rush-panel-head"><div><span className="rush-eyebrow">FULL MODELED SERVICE · SAME EXOGENOUS DRAWS</span><h3>Does connecting the decisions help?</h3></div><span className="rush-pill pale">Seed {data.request.seed}</span></div>
        {connected && separate && <div className="rush-outcomes"><div><span>Connected contribution</span><strong>{money(connected.contribution_cents)}</strong><small>After modeled food, fees and discounts</small></div><div><span>Accepted rush promises met</span><strong>{connected.existing_on_time}<em> / {connected.existing_orders}</em></strong><small>All original promises stay in the score</small></div><div><span>Average handoff wait</span><strong>{connected.avg_wait_minutes.toFixed(1)}<em> min</em></strong><small>Separate campaigns: {separate.avg_wait_minutes.toFixed(1)} min</small></div><div><span>Worst pickup wait</span><strong>{connected.worst_pickup_wait_minutes}<em> min</em></strong><small>Pickup customers remain visible</small></div></div>}
        <div className="rush-table-scroll"><table className="rush-results"><thead><tr><th>Controller</th><th>Contribution</th><th>Rush on time</th><th>New web orders</th><th>Handoff wait</th><th>Food holding</th><th>Spend</th></tr></thead><tbody>{Object.values(data.runs).map(r => <tr key={r.mode} className={r.mode === "coordinated" ? "featured" : ""}><td><button onClick={() => { setMode(r.mode); setTab("service"); }}>{r.label}{r.mode === "coordinated" && <span>SHARED STATE</span>}</button></td><td>{money(r.metrics.contribution_cents)}</td><td>{r.metrics.existing_on_time}/{r.metrics.existing_orders}</td><td>{r.metrics.visitor_orders}</td><td>{r.metrics.avg_wait_minutes.toFixed(1)} min</td><td>{r.metrics.food_hold_minutes} min</td><td>{money(r.metrics.promo_spend_cents)}</td></tr>)}</tbody></table></div>
        <details className="rush-assumptions"><summary>What these results mean</summary><p>Every order and customer response is synthetic. All controllers share the same underlying arrivals and buyer preferences; offers can change buyer choices. Contribution includes defined food costs, channel fees and discounts, and excludes overhead. A higher contribution can come with worse service. Overload and missed promises remain visible. Cooking estimates use completed observations; future actual durations are unavailable to the controller.</p><p>The simulated campaign adapter changes this preview only. DoorDash campaign access, update cadence and the station-aware feature gap are unverified assumptions to discuss with the sponsor.</p><pre>{JSON.stringify(data.assumptions, null, 2)}</pre></details>
      </section>
    </>}
  </div>;
}

function Timeline({ run, frame, minute, select }: { run: RushRun; frame: Frame; minute: number; select: (id: string) => void }) {
  const left = Math.max(0, minute - 4), right = left + 35;
  const past: Reservation[] = run.actual_tasks.filter(t => t.start != null && t.start < minute).map(t => ({ ...t, end: Math.min(t.end ?? minute, minute) }));
  const rows = [...past, ...frame.plan.filter(t => t.end > minute)];
  return <div className="rush-timeline" data-testid="station-timeline"><div className="rush-timeline-head"><span>STATION RESERVATIONS</span><span>Solid: observed · pale: estimated</span></div><div className="rush-axis"><span />{Array.from({ length: 8 }, (_, i) => <span key={i}>{time(left + i * 5)}</span>)}</div>{["fryer", "noodles", "assembly", "packing"].map(s => <div className="rush-lane" key={s}><b>{stationName[s]}</b><div>{rows.filter(r => r.station === s && r.end > left && r.start < right).map((r, i) => { const order = frame.orders.find(o => o.id === r.order_id); const start = Math.max(r.start, left), end = Math.min(r.end, right); return <button key={`${r.task_id}-${i}`} onClick={() => select(r.order_id)} title={`${r.order_id} · ${time(r.start)}–${time(r.end)}`} aria-label={`${r.order_id} ${stationName[s]} reservation`} className={`${order?.channel || "pickup"} ${r.start >= minute ? "forecast" : ""}`} style={{ left: `${(start - left) / 35 * 100}%`, width: `${Math.max(0.5, (end - start) / 35 * 100)}%` }}>{end - start >= 3 ? r.order_id : ""}</button>; })}<i className="rush-now" style={{ left: `${(minute - left) / 35 * 100}%` }} /></div></div>)}<div className="rush-legend"><span><i className="doordash" />DoorDash</span><span><i className="ubereats" />Uber Eats</span><span><i className="pickup" />Pickup / first-party</span><span>Now {time(minute)}</span></div></div>;
}

