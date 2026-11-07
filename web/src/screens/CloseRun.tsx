import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate, useSearchParams } from "react-router-dom";
import { api, stream } from "../api/client";
import type { CloseDetail, Finding, StepStatus } from "../api/types";
import { Page } from "../components/Page";
import { tri, type DayReview } from "../api/tri";
import { Status } from "../components/review";
import { ErrorBox, NumberField, SkeletonCard, Tween, useLoad } from "../components/ui";
import { fmtMonthDay } from "../lib/dates";
import { useApp, useToast } from "../state";
import { Own, useAgents, type AgentKey } from "../agents";

const AGENTS: [string, string][] = [
  ["books", "Books"], ["stock", "Stock"], ["analyst", "Analyst"], ["demand", "Demand"],
  ["plan", "Plan"], ["sentinel", "Sentinel"], ["report", "Report"], ["guard", "Guard"],
];
const AGENTS_K = AGENTS.map(([k]) => k);
const LABEL: Record<StepStatus, string> = { queued: "Queued", running: "Working", done: "Done", failed: "Failed", skipped: "Skipped" };
const DOT: Record<StepStatus, string> = { queued: "#8b938e", running: "#b8e986", done: "#0ca30c", failed: "#d03b3b", skipped: "#8b938e" };

function timeOf(ts: string) {
  const m = ts.match(/T(\d{2}):(\d{2})/);
  if (!m) return ts;
  const h = Number(m[1]);
  return `${h % 12 === 0 ? 12 : h % 12}:${m[2]} ${h >= 12 ? "pm" : "am"}`;
}

interface LogLine { ts: string; who: string; text: string }

export default function CloseRun() {
  const [sp] = useSearchParams();
  const runId = sp.get("run");
  const { date: gdate, setDate } = useApp();
  const nav = useNavigate();
  const toast = useToast();
  const { pulse, setRunning } = useAgents();
  const date = sp.get("date") || gdate || "";
  // a live run pins the global date to the night being closed; changing the date leaves the run
  useEffect(() => { const d = sp.get("date"); if (d && d !== gdate) setDate(d); }, [sp.get("date")]); // eslint-disable-line
  useEffect(() => { if (runId && sp.get("date") && gdate && gdate !== sp.get("date")) nav("/review/close", { replace: true }); }, [gdate]); // eslint-disable-line
  const [starting, setStarting] = useState(false);
  const { store } = useApp();
  const [ask, setAsk] = useState(false);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const runClose = async () => {
    setStarting(true); setAsk(false);
    try {
      const pc = Object.fromEntries(Object.entries(counts).map(([k, v]) => [k.toLowerCase(), Math.max(0, v)]));
      const r = await api.startClose(Object.keys(pc).length ? { date, portion_counts: pc, force: true } : { date, force: true }); nav(`/review/close?run=${encodeURIComponent(r.run_id)}&date=${r.date}`); }
    catch (e) { toast(String((e as Error).message), "crit"); }
    finally { setStarting(false); }
  };
  const [steps, setSteps] = useState<Record<string, { status: StepStatus; message?: string }>>(
    Object.fromEntries(AGENTS.map(([k]) => [k, { status: "queued" as StepStatus }])));
  const [log, setLog] = useState<LogLine[]>([]);
  const [found, setFound] = useState<Finding[]>([]);
  const [done, setDone] = useState<{ status: string; seconds: number } | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const t0 = useRef(Date.now());
  const detail = useLoad<CloseDetail | null>(async () => {
    if (!date || (runId && !done)) return null;
    // the close file is written just after `done`; retry briefly until it reflects this run
    for (let i = 0; i < 8; i++) {
      const r = await api.close(date).catch(() => null);
      const urgent = (r?.findings || []).filter((f) => f.urgency === "urgent").length;
      if (r && !(urgent > 0 && (r.alerts || []).length === 0)) return r;
      await new Promise((ok) => setTimeout(ok, 400));
    }
    return api.close(date).catch(() => null);
  }, [date, runId, done]);

  useEffect(() => {
    if (!runId) return;
    t0.current = Date.now();
    setSteps(Object.fromEntries(AGENTS.map(([k]) => [k, { status: "queued" as StepStatus }]))); setFound([]); setDone(null);
    const now = () => new Date().toLocaleTimeString("en-US", { hour12: false });
    setLog([{ ts: now(), who: "You", text: "Close shift" }]);
    setRunning("coordinator", true); pulse("coordinator", "started the close");
    const stop = stream(`/close/${encodeURIComponent(runId)}/events`, {
      step: (e: { step: string; status: StepStatus; message?: string }) => {
        setSteps((s) => ({ ...s, [e.step]: { status: e.status, message: e.message || s[e.step]?.message } }));
        setRunning(e.step, e.status === "running");
        if (e.status !== "running") pulse(e.step, (e.message || (typeof (e as { seconds?: number }).seconds === "number" ? `${e.status} in ${(e as { seconds?: number }).seconds}s` : e.status)).replace(/^./, (c) => c.toLowerCase()));
        if (e.message) setLog((l) => [...l, { ts: now(), who: AGENTS.find((a) => a[0] === e.step)?.[1] || e.step, text: e.message! }]);
      },
      finding: (f: Finding) => { setFound((x) => [...x, f]); if (f.urgency === "urgent") pulse("sentinel", `flagged ${(f.title || f.kind).replace(/^./, (c) => c.toLowerCase())}`); },
      done: (d: { status: string; seconds: number }) => { setDone(d); AGENTS_K.forEach((k) => setRunning(k, false)); setRunning("coordinator", false); pulse("coordinator", `close ${d.status} in ${d.seconds}s`); toast(`Close ${d.status} in ${d.seconds}s`, d.status === "done" ? "good" : "crit"); setLog((l) => [...l, { ts: now(), who: "Coordinator", text: `Close ${d.status} in ${d.seconds}s` }]); },
      error: (e: { message: string }) => setErr(e.message),
    });
    return stop;
  }, [runId]);

  // the new review step: the Review agent runs at the end of the close; its result is read back here
  const [rv, setRv] = useState<DayReview | null>(null);
  const [rvBusy, setRvBusy] = useState(false);
  useEffect(() => {
    if (!date || (runId && !done)) { setRv(null); return; }
    let on = true;
    const pull = (n: number) => tri.review.day(date).then((r) => {
      if (!on) return;
      setRv(r);
      if (runId && done && r.status !== "done" && !r.well.length && n < 6) setTimeout(() => pull(n + 1), 1500);
      else if (r.well.length || r.wrong.length) pulse("review", `${r.wrong.length} went wrong, ${r.actions.length} action items`);
    }).catch(() => on && setRv(null));
    pull(0);
    return () => { on = false; };
  }, [date, runId, done]); // eslint-disable-line
  const runReview = async () => {
    setRvBusy(true); setRunning("review", true);
    try { await tri.review.run(date); setRv(await tri.review.day(date)); pulse("review", "day review written"); }
    catch (e) { toast(`Review agent: ${(e as Error).message}`, "crit"); }
    finally { setRvBusy(false); setRunning("review", false); }
  };
  const hasReview = !!rv && (rv.well.length + rv.wrong.length + rv.causes.length) > 0;

  // Without a live run, show the last close as finished.
  const static_ = !runId;
  const d = detail.data;
  const view = useMemo(() => {
    if (!static_ || !d) return null;
    const byStep = Object.fromEntries(d.log.map((l) => [l.step, l]));
    return Object.fromEntries(AGENTS.map(([k]) => [k, { status: ((byStep[k]?.status as StepStatus) || "done"), message: undefined }]));
  }, [static_, d]);
  const st = view || steps;
  // one-line outcome per agent for a finished close
  const outcome = useMemo<Record<string, string>>(() => {
    if (!d) return {};
    const f = (k: string) => d.findings.find((x) => x.kind === k)?.title;
    const c = d.card?.[0];
    const sent = (d.alerts || []).find((a) => a.body);
    const secs = Object.fromEntries(d.log.map((l) => [l.step, l.seconds]));
    const o: Record<string, string> = {
      books: f("cash_short") || f("payout_short") || "Books balanced",
      stock: d.sold_out ? `Chashu sold out ${d.sold_out.at.toLowerCase()}` : "Stock counted",
      analyst: `${d.findings.length} findings`,
      demand: d.demand ? `${Math.round(d.demand.p50)} orders tomorrow` : "",
      plan: c ? `Make ${c.prep} ${c.item.toLowerCase()}` : "",
      sentinel: sent ? "Text sent" : (d.alerts || []).some((a) => a.status === "duplicate_suppressed") ? "Already texted" : "No text",
      report: "Report stored",
      guard: d.approved ? "Armed" : "Waiting for approval",
    };
    for (const k of Object.keys(o)) if (secs[k] !== undefined) o[`${k}_s`] = `${secs[k].toFixed(2)}s`;
    return o;
  }, [d]);
  const nDone = Object.values(st).filter((s) => s.status === "done" || s.status === "skipped").length;
  const finished = static_ ? !!d : !!done;
  const rank = (f: Finding) => (f.urgency === "urgent" ? 0 : f.urgency === "important" ? 1 : 2);
  const findings = (static_ && d ? d.findings : found)
    .filter((f) => f.urgency === "urgent" || f.urgency === "important")
    .map((f, i) => ({ f, i })).sort((a, b) => rank(a.f) - rank(b.f) || a.i - b.i).slice(0, 6).map((x) => x.f);
  const alerts = d?.alerts || [];
  const dup = alerts.some((a) => a.status === "duplicate_suppressed");
  const held = alerts.find((a) => (a.status || "").startsWith("held"));
  const text = alerts.find((a) => a.body)?.body;
  const outbox = useLoad(() => (finished && dup ? api.outbox().catch(() => []) : Promise.resolve([])), [finished, dup]);
  const sentAt = (outbox.data || []).find((m) => m.channel === "sms" && (m as { direction?: string }).direction !== "in"
    && !["reply", "received"].includes(m.status || "") && !(m.status || "").startsWith("held"))?.ts;
  const urgentCount = (d?.findings || []).filter((f) => f.urgency === "urgent").length;
  const loadingText = finished && (!d || (urgentCount > 0 && alerts.length === 0));
  const textTitle = loadingText ? "Checking what Sentinel sent…" : dup ? (sentAt ? `Text already sent at ${timeOf(sentAt)}` : "Text already sent tonight")
    : held ? "Text held until 8 am" : text ? "Text sent to Maya" : "No text: nothing urgent";
  const textBody = dup ? null : held ? held.body : text;

  return (
    <Page title="Review" live={false} actions={<button className="btn" onClick={() => { setCounts(Object.fromEntries((store?.limited_items?.length ? store.limited_items : ["Chashu"]).map((i) => [i, counts[i] ?? 0]))); setAsk(true); }} disabled={starting || (!!runId && !done) || !date}>{starting ? "Starting" : d || runId ? "Run again" : "Run close"}</button>}>
      {err && <ErrorBox error={err} />}
      {ask && <div className="scrim" onMouseDown={() => setAsk(false)}>
        <div className="modal" role="dialog" aria-modal="true" aria-labelledby="close-title" onMouseDown={(e) => e.stopPropagation()}
          onKeyDown={(e) => { if (e.key === "Escape") setAsk(false); if (e.key === "Enter") runClose(); }}>
          <h2 id="close-title">Close {fmtMonthDay(date)}</h2>
          {Object.keys(counts).map((it, i) => (
            <div className="stepper" key={it} style={{ gridTemplateColumns: "1fr auto" }}>
              <label htmlFor={`cnt-${it}`} style={{ fontWeight: 600 }}>{it} left</label>
              <NumberField id={`cnt-${it}`} value={counts[it]} onChange={(v) => setCounts((c) => ({ ...c, [it]: v }))} style={{ width: 96, textAlign: "center" }} label={`${it} left`} />
            </div>
          ))}
          <div style={{ display: "flex", gap: 10, justifyContent: "flex-end", marginTop: 6 }}>
            <button className="btn light" onClick={() => setAsk(false)}>Cancel</button>
            <button className="btn" onClick={runClose} disabled={starting} data-testid="start-close">{starting ? "Starting" : "Start the close"}</button>
          </div>
        </div>
      </div>}
      {static_ && !d && detail.loading && <SkeletonCard h={180} />}
      {static_ && !d && !detail.loading && <div className="card empty">No close for {date ? fmtMonthDay(date) : "this night"}</div>}

      {(runId || d) && <>
        <div style={{ background: "var(--ink)", color: "#fff", borderRadius: 6, padding: "18px 28px", display: "flex", alignItems: "center", gap: 24 }}>
          <span style={{ whiteSpace: "nowrap" }}><b style={{ color: "var(--mint)" }}><Tween value={nDone} /> of {AGENTS.length} done</b></span>
          <div style={{ flex: 1, height: 10, background: "#2b3833" }} role="progressbar" aria-valuenow={nDone} aria-valuemax={AGENTS.length}>
            <div style={{ width: `${(nDone / AGENTS.length) * 100}%`, height: "100%", background: "var(--mint)", transition: "width .4s" }} />
          </div>
          <span style={{ whiteSpace: "nowrap" }}>{finished ? (done ? `Finished in ${done.seconds}s` : d ? `${d.status === "done" ? "Finished" : d.status} in ${d.seconds}s` : "Finished") : "Running"}</span>
        </div>

        <div className="grid4" style={{ gap: 18 }}>
          {AGENTS.map(([k, name], idx) => {
            const s = st[k] || { status: "queued" };
            const working = s.status === "running";
            const queued = s.status === "queued";
            return (
              <div key={`${k}-${runId || "s"}`} className={`card agent enter${working ? " working" : ""}`} aria-live="polite" style={{
                background: working ? "var(--green)" : queued ? "var(--soft)" : "var(--paper)", color: working ? "#fff" : undefined, minHeight: 150,
                display: "flex", flexDirection: "column", transition: "background .25s, color .25s", animationDelay: `${idx * 40}ms`,
              }}>
                <h3>{name}</h3><Own a={k as AgentKey} dark={working} />
                <div style={{ fontSize: 15, marginTop: 10, flex: 1, color: queued ? "var(--muted)" : undefined }}>{s.message || (queued ? "Waiting" : finished && static_ ? outcome[k] : "")}</div>
                <div style={{ display: "flex", alignItems: "center", gap: 8, fontSize: 14.5, fontWeight: 600, color: working ? "var(--mint)" : queued ? "var(--muted)" : undefined, marginTop: 8 }}>
                  <i className="dot" style={{ background: DOT[s.status] }} />{LABEL[s.status]}{static_ && outcome[`${k}_s`] ? <span className="ink2 num" style={{ marginLeft: "auto", fontWeight: 500 }}>{outcome[`${k}_s`]}</span> : null}
                </div>
              </div>
            );
          })}
        </div>

        <div className="closegrid">
          <div className="card">
            <h3 style={{ marginBottom: 10 }}>Log</h3>
            {(static_ && d ? d.log.map((l) => ({ ts: `${l.seconds.toFixed(2)}s`, who: l.step, text: `${l.status.charAt(0).toUpperCase()}${l.status.slice(1)}${l.error ? `: ${l.error}` : ""}` })) : log).map((l, i) => (
              <div key={i} className="enter" style={{ display: "grid", gridTemplateColumns: "90px 120px 1fr", gap: 10, padding: "5px 0", fontSize: 15 }}>
                <span className="muted num">{l.ts}</span><b style={{ fontWeight: 600, textTransform: "capitalize" }}>{l.who}</b><span>{l.text}</span>
              </div>
            ))}
          </div>
          <div className="card cream">
            <h3 style={{ marginBottom: 10 }}>Findings</h3>
            {findings.length === 0 && <div className="ink2">–</div>}
            {findings.map((f, i) => (
              <div key={`${f.title}-${i}`} className="enter" style={{ display: "grid", gridTemplateColumns: "18px 1fr", gap: 8, padding: "7px 0" }}>
                <i className="dot" style={{ background: f.urgency === "urgent" ? "var(--crit)" : f.urgency === "important" ? "var(--ser)" : "var(--good)", marginTop: 7 }} />
                <div><div style={{ fontSize: 15.5 }}>{f.title || f.kind}</div>
                  </div>
              </div>
            ))}
          </div>
        </div>

        {finished && (
          <div className="card reviewstep" data-testid="review-step"><Own a="review" />
            <div className="cardhead"><h3>Review</h3>
              {hasReview ? <Link className="link" to="/review/day" style={{ fontSize: 14 }}>Open day review</Link>
                : <button className="btn small" onClick={runReview} disabled={rvBusy}>{rvBusy ? "Review agent working" : "Run review"}</button>}</div>
            {!rv && <div className="ink2">Waiting for the Review agent</div>}
            {rv && !hasReview && <div className="ink2">{rvBusy ? "Writing" : "Not run yet"}</div>}
            {rv && hasReview && <div className="rsteps">
              <div><b className="num">{rv.well.length}</b><span className="ink2">went well</span></div>
              <div><b className="num crit">{rv.wrong.length}</b><span className="ink2">went wrong</span></div>
              <div><b className="num">{rv.causes.length}</b><span className="ink2">causes</span></div>
              <div><b className="num">{rv.actions.length}</b><span className="ink2">action items</span></div>
              <div><b className="num">{rv.kb_changes.length}</b><span className="ink2">knowledge changes</span></div>
              {rv.wrong[0] && <p className="rfirst">{rv.wrong[0].text}</p>}
              {rv.kb_changes.some((k) => k.status === "needs_approval") && <p className="rfirst"><Status s="needs_approval" /> <Link className="link" to="/review/knowledge">Approve in Knowledge</Link></p>}
            </div>}
          </div>
        )}

        {finished && (
          <div className="card" style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 20, alignItems: "center" }}>
            <div>
              <h3>{textTitle}</h3>
              {textBody && <div style={{ marginTop: 6, fontSize: 15.5, maxWidth: 900 }}>{textBody}</div>}
            </div>
            <div style={{ display: "flex", gap: 10 }}>
              <Link className="btn light" to="/past/reports">Report</Link>
              <Link className="btn" to="/future/tomorrow">Review tomorrow's card</Link>
            </div>
          </div>
        )}
      </>}
    </Page>
  );
}
