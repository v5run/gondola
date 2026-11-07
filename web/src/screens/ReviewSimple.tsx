/** Review › Needs attention and Review › End of day: short lists with one action each. */
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tri, sevRank, type DayReview, type ExceptionItem } from "../api/tri";
import { Page } from "../components/Page";
import { ErrorBox, Skeleton } from "../components/ui";
import { fmtDay } from "../lib/dates";
import { useApp, useToast } from "../state";

const DECISION: Record<string, string> = { alert: "Manager was texted", present: "Handed to the kitchen controls", note: "Saved for end of day" };

export function Attention() {
  const { date } = useApp();
  const toast = useToast();
  const [items, setItems] = useState<ExceptionItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!date) return;
    let on = true;
    setItems(null); setErr(null);
    tri.review.exceptions(date).then((x) => on && setItems(x)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [date, n]);
  const open = (items || []).filter((x) => !x.resolved).sort((a, b) => sevRank(a.severity) - sevRank(b.severity));
  const done = (items || []).length - open.length;
  const resolve = async (x: ExceptionItem) => {
    try { await tri.review.resolve(x.id, date); setItems((l) => (l || []).map((y) => (y.id === x.id ? { ...y, resolved: true } : y))); toast("Marked as handled", "good"); }
    catch (e) { toast(`Couldn't update: ${(e as Error).message}`, "crit"); }
  };
  return (
    <Page title="Review">
      {err && <ErrorBox error={err} retry={() => setN((x) => x + 1)} />}
      {!items && !err && <Skeleton h={260} />}
      {items && <div className="card">
        <h2 className="rv-h">{open.length === 0 ? "Nothing needs you right now" : `${open.length} thing${open.length > 1 ? "s" : ""} need${open.length > 1 ? "" : "s"} attention`}</h2>
        <p className="ink2">{fmtDay(date)}{done ? ` · ${done} already handled` : ""}</p>
        <ul className="rv-list">
          {open.map((x) => {
            const sev = sevRank(x.severity);
            return (
              <li key={x.id} className={sev === 0 ? "rv-crit" : sev === 1 ? "rv-warn" : ""}>
                <div><b>{x.title.replace(/^./, (c) => c.toUpperCase())}</b><span>{x.note}</span><small>{x.ts?.slice(11, 16)} · {DECISION[x.decision] || x.decision}</small></div>
                <button className="btn light small" onClick={() => resolve(x)}>Mark handled</button>
              </li>
            );
          })}
        </ul>
      </div>}
    </Page>
  );
}

export function EndOfDay() {
  const { date } = useApp();
  const toast = useToast();
  const [rv, setRv] = useState<DayReview | null>(null);
  const [state, setState] = useState<"loading" | "none" | "ok">("loading");
  const [busy, setBusy] = useState(false);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!date) return;
    let on = true;
    setState("loading"); setRv(null);
    tri.review.day(date).then((x) => { if (on) { setRv(x); setState("ok"); } }).catch(() => on && setState("none"));
    return () => { on = false; };
  }, [date, n]);
  const run = async () => {
    setBusy(true);
    try { await tri.review.run(date); setN((x) => x + 1); toast("End-of-day review is ready", "good"); }
    catch (e) { toast(`Review failed: ${(e as Error).message}`, "crit"); }
    finally { setBusy(false); }
  };
  const actions = rv?.actions || [];
  return (
    <Page title="Review">
      {state === "loading" && <Skeleton h={300} />}
      {state === "none" && <div className="card rv-empty">
        <h2 className="rv-h">No end-of-day review for {fmtDay(date)} yet</h2>
        <p className="ink2">Close the shift first, then run the review.</p>
        <div className="rv-btns"><Link className="btn" to="/review/close">Close shift</Link><button className="btn light" onClick={run} disabled={busy}>{busy ? "Reviewing…" : "Run review"}</button></div>
      </div>}
      {state === "ok" && rv && <>
        <div className="rv-cols">
          <div className="card"><h3>Went wrong</h3>
            {rv.wrong.length === 0 ? <p className="ink2 ps-gap">Nothing notable.</p> : <ul className="ps-points">{rv.wrong.slice(0, 3).map((w) => <li key={w.text} className="pt-bad"><i aria-hidden>!</i>{w.text}</li>)}</ul>}
          </div>
          <div className="card"><h3>Went well</h3>
            {rv.well.length === 0 ? <p className="ink2 ps-gap">Nothing notable.</p> : <ul className="ps-points">{rv.well.slice(0, 3).map((w) => <li key={w.text} className="pt-good"><i aria-hidden>✓</i>{w.text}</li>)}</ul>}
          </div>
        </div>
        {actions.length > 0 && <div className="card"><h3>Do next</h3>
          <ul className="ps-points">{actions.slice(0, 3).map((a) => <li key={a.id}><i aria-hidden>→</i><span>{a.text}{a.owner ? <small className="ink2"> · {a.owner}</small> : null}</span></li>)}</ul>
          <Link className="link" to="/review/actions">All to-dos →</Link>
        </div>}
        <div className="rv-btns"><Link className="btn light" to="/review/close">Close shift</Link><Link className="link" to="/review/day">Causes and evidence →</Link></div>
      </>}
    </Page>
  );
}
