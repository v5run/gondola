import { useEffect, useState } from "react";
import { tri, type ContextPayload, type Digest } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { evidenceList } from "../components/review";
import { ErrorBox, HBarInline, Segmented, Skeleton, shortDate } from "../components/ui";
import { fmtMonth } from "../lib/dates";
import { useApp } from "../state";
import { Own } from "../agents";

const AGENTS: [string, string][] = [["rush", "Rush agent"], ["exceptions", "Exceptions agent"], ["review", "Review agent"]];
const OWNER: Record<string, string> = { rush: "rush", exceptions: "exceptions", review: "review" };
const NUM_NAME: Record<string, string> = { orders: "Orders", promises_met: "Promises met", promises_met_pct: "Promises met", worst_wait_min: "Worst wait", late: "Late", late_orders: "Late", forecast_error_pct: "Forecast error", cancels: "Cancels", net_sales: "Net sales" };

/** Review › Memory: the digests agents read instead of old reports, and exactly what each agent gets. */
export default function Memory() {
  const { date } = useApp();
  const [kind, setKind] = useState("day");
  const [dg, setDg] = useState<Digest[] | null>(null);
  const [dErr, setDErr] = useState<string | null>(null);
  const [agent, setAgent] = useState("rush");
  const [cx, setCx] = useState<ContextPayload | null>(null);
  const [cErr, setCErr] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    setDg(null); setDErr(null);
    tri.review.digests(kind, 400).then((l) => on && setDg([...l].sort((a, b) => String(b.period).localeCompare(String(a.period))).slice(0, 40))).catch((e) => on && setDErr(String(e.message)));
    return () => { on = false; };
  }, [kind]);
  useEffect(() => {
    if (!date) return;
    let on = true;
    setCx(null); setCErr(null);
    tri.review.context(agent, date).then((x) => on && setCx(x)).catch((e) => on && setCErr(String(e.message)));
    return () => { on = false; };
  }, [agent, date]);
  const budget = cx ? cx.budget_tokens ?? cx.budget ?? null : null;
  const payload = cx ? cx.payload ?? Object.fromEntries(Object.entries(cx).filter(([k]) => !["agent", "date", "tokens", "budget", "budget_tokens", "dropped", "now"].includes(k))) : null;
  const dropped = cx?.dropped && Array.isArray(cx.dropped) ? cx.dropped : [];
  return (
    <Page title="Review" live={false}>
      <div className="memory-grid">
        <div className="card"><Own a="review" /><Info k="digests" />
          <div className="cardhead"><h3>Digests</h3><Segmented label="Digest" value={kind} onChange={setKind} options={[["shift", "Shift"], ["day", "Day"], ["week", "Week"], ["month", "Month"]]} /></div>
          {dErr && <ErrorBox error={dErr} />}
          {!dg && !dErr && <Skeleton h={300} />}
          {dg && dg.length === 0 && <div className="empty">None yet</div>}
          <div className="dglist" data-testid="digests">
            {dg?.map((d) => {
              const bullets = Array.isArray(d.summary) ? d.summary : d.bullets?.length ? d.bullets : String(d.summary || "").split(/(?<=\.)\s+/).filter(Boolean);
              const nums = Object.entries(d.numbers || {}).filter(([, v]) => typeof v === "number").slice(0, 4);
              return (
                <div key={d.id} className="dgrow" data-id={d.id}>
                  <b className="dgp">{d.kind === "month" ? fmtMonth(d.period) : /^\d{4}-\d{2}-\d{2}$/.test(d.period) ? `${d.kind === "week" ? "Week of " : ""}${shortDate(d.period)}` : d.period}</b>
                  <div>
                    <ul>{bullets.slice(0, 5).map((b, i) => <li key={i}>{b}</li>)}</ul>
                    {nums.length > 0 && !/\d/.test(bullets.join(" ")) && <div className="dgnums">{nums.map(([k, v]) => <span key={k}><span className="ink2">{NUM_NAME[k] || k.replace(/_/g, " ")}</span> <b className="num">{fmtNum(k, v as number)}</b></span>)}</div>}
                    {evidenceList(d.wrong ?? d.wrong_themes).length > 0 && <ul className="dgwrong">{evidenceList(d.wrong ?? d.wrong_themes).slice(0, 3).map((w, i) => <li key={i}>{w}</li>)}</ul>}
                  </div>
                </div>
              );
            })}
          </div>
        </div>
        <div className="card ctxcard"><Own a={OWNER[agent]} /><Info k="context" />
          <div className="cardhead"><h3>Context</h3></div>
          <Segmented label="Agent" value={agent} onChange={setAgent} options={AGENTS} />
          {cErr && <ErrorBox error={cErr} />}
          {!cx && !cErr && <Skeleton h={300} />}
          {cx && <>
            <div className="ctxbudget" data-testid="context-tokens">
              <b className="num">{cx.tokens.toLocaleString("en-US")}</b><span className="ink2">tokens{budget ? ` of ${budget.toLocaleString("en-US")}` : ""}<Info k="tokens" inline /></span>
              {budget ? <HBarInline v={cx.tokens / budget} color={cx.tokens > budget ? "var(--crit)" : "var(--green)"} /> : null}
            </div>
            {dropped.length > 0 && <div className="ink2" style={{ fontSize: 13.5 }}>Dropped to fit: {dropped.map((x) => (typeof x === "string" ? x : JSON.stringify(x))).join(", ")}</div>}
            <div className="ctxsecs" data-testid="context">
              {payload && typeof payload === "object" && Object.entries(payload as Record<string, unknown>).map(([k, v]) => (
                <details key={`${agent}-${k}`} className="ctxsec" open={Object.keys(payload as object).length <= 4}>
                  <summary><b>{k.replace(/_/g, " ")}</b><span className="ink2 num">{size(v)}</span></summary>
                  <pre>{JSON.stringify(v, null, 2)}</pre>
                </details>
              ))}
            </div>
          </>}
        </div>
      </div>
    </Page>
  );
}

const fmtNum = (k: string, v: number) => (/pct|rate/.test(k) || (k === "promises_met" && v <= 1) ? `${Math.round(v <= 1 && !/pct/.test(k) ? v * 100 : v)}%` : /min/.test(k) ? `${Math.round(v)} min` : Math.round(v).toLocaleString("en-US"));
const size = (v: unknown) => (Array.isArray(v) ? `${v.length}` : v && typeof v === "object" ? `${Object.keys(v).length}` : "");
