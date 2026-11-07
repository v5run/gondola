import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { tri, type DayReview as DR, type Evidenced } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { Evidence, Status, measureText } from "../components/review";
import { ErrorBox, SkeletonCard, clock, longDate, shortDate } from "../components/ui";
import { useApp, useToast } from "../state";
import { Own, useAgents } from "../agents";

export default function DayReview() {
  const { date, now } = useApp();
  const toast = useToast();
  const { pulse, setRunning } = useAgents();
  const [r, setR] = useState<DR | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    if (!date) return;
    let on = true;
    setR(null); setErr(null);
    tri.review.day(date).then((x) => on && setR(x)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [date]);
  const closed = !!now && (date < now.today || now.phase === "closed");
  const has = !!r && (r.well.length + r.wrong.length + r.causes.length + r.actions.length) > 0;
  const run = async () => {
    setBusy(true); setRunning("review", true);
    try {
      const x = await tri.review.run(date);
      const d = x && "well" in x ? (x as DR) : await tri.review.day(date);
      setR(d);
      pulse("review", `reviewed ${shortDate(date)}: ${d.wrong.length} wrong, ${d.actions.length} actions`);
      toast("Day review written", "good");
    } catch (e) { toast(`Review agent: ${(e as Error).message}`, "crit"); }
    finally { setBusy(false); setRunning("review", false); }
  };
  const actions = <button className="btn" onClick={run} disabled={busy || !closed} title={closed ? undefined : `Unlocks at close (${now ? clock(now.close) : ""})`} data-testid="run-review">
    {busy ? "Review agent working" : has ? "Run again" : "Run review"}</button>;
  return (
    <Page title="Review" live={false} actions={actions}>
      {err && <ErrorBox error={err} />}
      {!r && !err && <SkeletonCard h={260} lines={6} />}
      {r && !has && <div className="card empty" data-testid="review-empty">
        {r.status === "open" || !closed ? `${longDate(date)} is still in service. The review runs at close.` : `No review for ${longDate(date)} yet`}</div>}
      {r && has && <>
        <div className="review3" data-testid="day-review">
          <Column title="Went well" tone="good" rows={r.well} />
          <Column title="Went wrong" tone="crit" rows={r.wrong} />
          <Column title="Why" tone="ink" rows={r.causes} />
        </div>
        <div className="review2">
          <div className="card"><Own a="review" /><Info k="action_items" />
            <div className="cardhead"><h3>Action items</h3><Link className="link" to="/review/actions" style={{ fontSize: 14 }}>All</Link></div>
            {r.actions.length === 0 && <div className="ink2">None</div>}
            {r.actions.map((a) => (
              <div key={a.id} className="airow">
                <div><b>{a.text}</b><div className="ink2">{[a.owner, a.check_on && `check ${shortDate(a.check_on)}`, measureText(a.measure)].filter(Boolean).join(" · ")}</div></div>
                <Status s={a.status} />
              </div>
            ))}
          </div>
          <div className="card"><Own a="review" /><Info k="knowledge" />
            <div className="cardhead"><h3>Remembered</h3><Link className="link" to="/review/knowledge" style={{ fontSize: 14 }}>Knowledge</Link></div>
            {r.kb_changes.length === 0 && <div className="ink2">No changes</div>}
            {r.kb_changes.map((k, i) => (
              <div key={`${k.id}-${i}`} className="airow">
                <div><b>{k.statement}</b><div className="ink2">{opName(k.op)} · {k.id}</div></div>
                <Status s={k.status} />
              </div>
            ))}
          </div>
        </div>
      </>}
    </Page>
  );
}

const opName = (op: string) => ({ add: "Added", update: "Updated", retire: "Retired", confirm: "Confirmed" } as Record<string, string>)[op] || op;

function Column({ title, tone, rows }: { title: string; tone: "good" | "crit" | "ink"; rows: Evidenced[] }) {
  return (
    <div className={`card rcol t-${tone}`}><Own a="review" /><Info k="day_review" />
      <div className="cardhead"><h3>{title}</h3></div>
      {rows.length === 0 && <div className="ink2">–</div>}
      {rows.map((x, i) => (
        <div key={i} className="rline enter" style={{ animationDelay: `${i * 40}ms` }}>
          <i className="dot" />
          <div><div>{x.text}</div><Evidence ev={x.evidence} /></div>
        </div>
      ))}
    </div>
  );
}
