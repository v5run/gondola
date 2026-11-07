import { useEffect, useState } from "react";
import { scanList, sevRank, tri, type ExceptionItem } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { Evidence } from "../components/review";
import { ErrorBox, Segmented, SkeletonCard, clock } from "../components/ui";
import { useApp, useToast } from "../state";
import { useExceptions } from "../live";
import { Own, useAgents } from "../agents";

const SEV: [RegExp, string, string][] = [[/crit|high|urgent/, "High", "var(--crit)"], [/warn|med/, "Warning", "var(--warn)"], [/.*/, "Info", "var(--muted)"]];
const sevOf = (s: string) => SEV.find(([r]) => r.test(s || ""))!;
const DECISION: Record<string, string> = { alert: "Alerted the manager", present: "Handed to Present", note: "Noted for the close" };

export default function Exceptions() {
  const { date, now } = useApp();
  const ex = useExceptions();
  const toast = useToast();
  const { pulse, setRunning } = useAgents();
  const isToday = !!now && date === now.today;
  const [other, setOther] = useState<ExceptionItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  const [show, setShow] = useState<"open" | "all">("open");
  const [busy, setBusy] = useState<string | null>(null);
  const [done, setDone] = useState<Set<string>>(new Set());
  useEffect(() => {
    if (!date || isToday) return;
    let on = true;
    setOther(null); setErr(null);
    tri.review.exceptions(date).then((l) => on && setOther(l)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [date, isToday, n]);
  const raw = isToday ? ex.list : other;
  const error = isToday ? (ex.list ? null : ex.error) : err;
  const list = (raw || []).map((x) => (done.has(x.id) ? { ...x, resolved: true } : x));
  const open = list.filter((x) => !x.resolved).sort((a, b) => sevRank(a.severity) - sevRank(b.severity) || b.ts.localeCompare(a.ts));
  const shown = show === "open" ? open : [...open, ...list.filter((x) => x.resolved)];
  const resolve = async (x: ExceptionItem) => {
    setBusy(x.id);
    try {
      await tri.review.resolve(x.id, date);
      setDone((s) => new Set(s).add(x.id));
      if (isToday) ex.resolveLocal(x.id);
      pulse("exceptions", `resolved: ${x.title.replace(/^./, (c) => c.toLowerCase())}`);
      toast("Resolved", "good");
    } catch (e) { toast(`Couldn't resolve: ${(e as Error).message}`, "crit"); }
    finally { setBusy(null); }
  };
  const scan = async () => {
    setBusy("scan"); setRunning("exceptions", true);
    try {
      const fresh = scanList(await tri.review.scan(date));
      toast(fresh.length ? `${fresh.length} new exception${fresh.length > 1 ? "s" : ""}` : "Nothing new", fresh.length ? "crit" : "good");
      pulse("exceptions", fresh.length ? `found ${fresh.length} new` : "scanned: nothing new");
      if (isToday) ex.reload(); else setN((x) => x + 1);
    } catch (e) { toast(`Scan failed: ${(e as Error).message}`, "crit"); }
    finally { setBusy(null); setRunning("exceptions", false); }
  };
  const actions = <div className="cardacts">
    <Segmented label="Show" value={show} onChange={(v) => setShow(v as "open" | "all")} options={[["open", `Open${raw ? ` ${open.length}` : ""}`], ["all", "All"]]} />
    <button className="btn small" onClick={scan} disabled={busy === "scan" || !date} data-testid="scan">{busy === "scan" ? "Scanning" : "Scan now"}</button>
  </div>;
  return (
    <Page title="Review" live={false}>
      {error && <ErrorBox error={error} retry={() => (isToday ? ex.reload() : setN((x) => x + 1))} />}
      {!raw && !error && <SkeletonCard h={300} lines={6} />}
      {raw && <div className="card exlist"><Own a="exceptions" /><Info k="exceptions" />
        <div className="cardhead"><h3>Exceptions</h3>{actions}</div>
        {shown.length === 0 && <div className="empty">{list.length ? "All resolved" : "Nothing unusual"}</div>}
        <div role="list" data-testid="exceptions">
          {shown.map((x) => {
            const [, sev, color] = sevOf(x.severity);
            return (
              <div key={x.id} role="listitem" className={`exrow enter${x.resolved ? " done" : ""}`} data-id={x.id} data-sev={sev.toLowerCase()}>
                <span className="exsev"><i className="dot" style={{ background: x.resolved ? "#c3cbc5" : color }} />{sev}</span>
                <span className="num muted">{clock(x.ts.slice(11, 16))}</span>
                <div className="exbody">
                  <b>{x.title}</b>
                  <div className="ink2">{DECISION[x.decision] || x.decision}{x.note ? ` · ${x.note}` : ""}</div>
                  <Evidence ev={x.evidence} max={4} />
                </div>
                {x.resolved ? <span className="ink2 exres">Resolved</span>
                  : <button className="btn small light" onClick={() => resolve(x)} disabled={busy === x.id} data-testid="resolve">{busy === x.id ? "Resolving" : "Resolve"}</button>}
              </div>
            );
          })}
        </div>
      </div>}
    </Page>
  );
}
