import { useEffect, useRef, useState } from "react";
import { tri, type Outlook } from "../api/tri";
import { usePlayback } from "../playback";

/** Agent results are explicit runs; the model and external-event source are separate modes. */
export function OutlookPanel({ date, onUpdate }: { date: string; onUpdate: () => void }) {
  const playback = usePlayback();
  const [result, setResult] = useState<Outlook | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const previous = useRef<string | null>(null);
  useEffect(() => {
    if (!date || playback.active) return;
    let live = true;
    previous.current = null;
    const load = () => tri.future.outlook(date).then((r) => {
      if (!live) return;
      const key = r.active ? r.run_id || "active" : "fallback";
      if (previous.current !== null && previous.current !== key) onUpdate();
      previous.current = key; setResult(r); setError(null);
    }).catch(() => { if (live) setError("Outlook status unavailable."); });
    load();
    const timer = setInterval(load, 60000);
    return () => { live = false; clearInterval(timer); };
  }, [date, playback.active]);
  const run = async () => {
    if (playback.active) return;
    setBusy(true); setError(null);
    try { const r = await tri.future.runOutlook(date); previous.current = r.active ? r.run_id || "active" : "fallback"; setResult(r); onUpdate(); }
    catch { setError("Outlook could not run. The existing forecast remains in use; wait a few seconds before retrying."); }
    finally { setBusy(false); }
  };
  const chosen = result?.events?.find((e) => e.id === result.scenario?.event_id);
  if (playback.active) return <p className="ink2">Playback is read-only. Exit Playback to investigate current demand signals.</p>;
  return <section className="card outlook-panel" aria-label="Outlook agent" data-testid="outlook-panel">
    <div className="outlook-head"><div><span className="lab">DEMAND INTELLIGENCE · DEMO</span><h3>Outlook agent</h3></div>
      <button className="btn" type="button" onClick={run} disabled={!date || busy} data-testid="run-outlook">{busy ? "Investigating…" : "Investigate signals"}</button></div>
    {error && <p role="alert">{error}</p>}
    {!result && !error && <p className="ink2">Checking outlook status…</p>}
    {result && <>
      <p className="outlook-status" data-testid="outlook-status"><b>{result.active ? "Agent scenario in use" : "ML fallback in use"}</b> · {result.reason}</p>
      {result.active && result.scenario && <>
        <div className="outlook-facts">
          <div><span>Agent estimate at run</span><b>{Math.round(result.scenario.total_p50)} orders</b></div>
          <div><span>ML reference at run{result.ml_reference?.agent_inspected ? " · inspected" : " · not inspected"}</span><b>{Math.round(result.ml_reference?.total.p50 ?? 0)} orders</b></div>
          <div><span>Anchor</span><b>{result.scenario.anchor === "ml" ? "ML forecast" : "Historical analogs"}</b></div>
        </div>
        <p>{chosen ? <><b>{chosen.title}</b> · {chosen.start} · {chosen.distance_km} km · {chosen.status} · mock event</> : "No event selected."}</p>
        <p>Agent-selected event assumption: <b>{result.scenario.assumed_pct > 0 ? "+" : ""}{result.scenario.assumed_pct}%</b>. {result.scenario.warning}</p>
        {result.interpretation && <ul>{result.interpretation.map((text) => <li key={text}>{text}</li>)}</ul>}
        <p className="ink2">{result.scenario.uncertainty} Weather source: {result.weather?.source || "not inspected"}. Events: fictional fixtures. All restaurant actions are simulated.</p>
        <details><summary>Evidence and tool trace</summary>
          <p>Tools: {result.tools_called?.join(" → ") || "none recorded"}.</p>
          <p>Considered events: {result.events?.map((e) => `${e.title} (${e.status}, ${e.distance_km} km)`).join("; ") || "none"}.</p>
          <p>Prior same-weekday completed orders: {result.analogs?.map((a) => `${a.date}: ${a.orders}`).join(", ") || "none"}. Historical comparisons are not causal.</p>
          <p>Run {result.run_id?.slice(0, 8)} · active for up to 60 store-clock minutes.</p>
        </details>
      </>}
      {!result.active && <p className="ink2">The baseline is being shown. To use the agent, configure ADK and a model, then investigate signals. Events remain fictional.</p>}
    </>}
  </section>;
}
