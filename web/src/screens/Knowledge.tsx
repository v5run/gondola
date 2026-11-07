import { useEffect, useState } from "react";
import { tri, type KbItem } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { Evidence, Status } from "../components/review";
import { ErrorBox, HBarInline, Segmented, SkeletonCard } from "../components/ui";
import { useToast } from "../state";
import { Own, useAgents } from "../agents";

const STATUS: [string, string][] = [["needs_approval", "Needs approval"], ["active", "Active"], ["proposed", "Proposed"], ["retired", "Retired"], ["", "All"]];
const KINDS: [string, string][] = [["", "All kinds"], ["event_effect", "Event effects"], ["item_behavior", "Item behavior"], ["capacity", "Capacity"], ["pricing", "Pricing"], ["ops_rule", "Rules"], ["action_item", "Action items"]];
const KIND_NAME = Object.fromEntries(KINDS) as Record<string, string>;

const scopeText = (s: Record<string, unknown> | null | undefined) =>
  Object.entries(s || {}).filter(([, v]) => v !== null && v !== undefined && v !== "").map(([k, v]) => (k === "weekday" || k === "daypart" || k === "event" || k === "item" ? String(v) : `${k.replace(/_/g, " ")} ${v}`)).join(" · ");
const effectText = (e: Record<string, unknown> | null | undefined) => {
  if (!e) return "";
  const pctv = e.change_pct ?? e.pct;
  if (typeof pctv === "number") return `${pctv > 0 ? "+" : "−"}${Math.abs(pctv)}% ${String(e.metric || "").replace(/_/g, " ")}${e.window ? ` · ${e.window}` : ""}`;
  return Object.entries(e).filter(([, v]) => typeof v !== "object").map(([k, v]) => `${k.replace(/_/g, " ")} ${typeof v === "number" ? Math.round(v * 100) / 100 : v}`).join(" · ");
};

export default function Knowledge() {
  const toast = useToast();
  const { pulse } = useAgents();
  const [status, setStatus] = useState("needs_approval");
  const [kind, setKind] = useState("");
  const [list, setList] = useState<KbItem[] | null>(null);
  const [counts, setCounts] = useState<Record<string, number>>({});
  const [err, setErr] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    let on = true;
    setErr(null);
    tri.review.kb(status || undefined, kind || undefined).then((l) => on && setList(l)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [status, kind, n]);
  useEffect(() => {
    tri.review.kb().then((l) => { const c: Record<string, number> = {}; for (const x of l) c[x.status] = (c[x.status] || 0) + 1; setCounts(c); }).catch(() => {});
  }, [n]);
  const act = async (it: KbItem, op: "approve" | "retire") => {
    setBusy(it.id);
    try {
      const r = op === "approve" ? await tri.review.approve(it.id) : await tri.review.retire(it.id);
      pulse("review", `${op === "approve" ? "approved" : "retired"} ${it.id}`);
      toast(op === "approve" ? (r.item?.status === "active" ? "Approved: now active" : `Approved: ${r.item?.status || "pending"}`) : "Retired", "good");
      setN((x) => x + 1);
    } catch (e) { toast(`Couldn't ${op}: ${(e as Error).message}`, "crit"); }
    finally { setBusy(null); }
  };
  const actions = <div className="cardacts">
    <select className="input slim" value={kind} onChange={(e) => setKind(e.target.value)} aria-label="Kind">{KINDS.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
    <Segmented label="Status" value={status} onChange={setStatus} options={STATUS.map(([v, l]) => [v, v && counts[v] ? `${l} ${counts[v]}` : l] as [string, string])} />
  </div>;
  return (
    <Page title="Review" date={false} live={false}>
      {err && <ErrorBox error={err} retry={() => setN((x) => x + 1)} />}
      {!list && !err && <SkeletonCard h={300} lines={6} />}
      {list && <div className="card"><Own a="review" /><Info k="knowledge" />
        <div className="cardhead"><h3>Knowledge</h3>{actions}</div>
        {list.length === 0 && <div className="empty">Nothing here</div>}
        <div className="kblist" role="list" data-testid="kb">
          {list.map((it) => {
            const approvable = it.status === "needs_approval" || (it.status === "proposed" && it.needs_approval);
            return (
              <div key={it.id} role="listitem" className={`kbrow enter${it.status === "retired" ? " done" : ""}`} data-id={it.id} data-status={it.status}>
                <div className="kbmain">
                  <b>{it.statement}</b>
                  <div className="ink2">{[KIND_NAME[it.kind] || it.kind, scopeText(it.scope), effectText(it.effect)].filter(Boolean).join(" · ")}</div>
                  <div className="kbev"><span className="ink2">{it.n} example{it.n === 1 ? "" : "s"}</span><Evidence ev={it.evidence} max={5} /></div>
                </div>
                <div className="kbconf" title="Confidence"><HBarInline v={it.confidence} /><span className="num">{it.confidence.toFixed(2)}</span><Info k="confidence" inline /></div>
                <Status s={it.status} />
                <div className="kbact">
                  {approvable && <button className="btn small" onClick={() => act(it, "approve")} disabled={busy === it.id} data-testid="approve">Approve</button>}
                  {it.status !== "retired" && it.status !== "rejected" && <button className="btn small light" onClick={() => act(it, "retire")} disabled={busy === it.id}>Retire</button>}
                </div>
              </div>
            );
          })}
        </div>
      </div>}
    </Page>
  );
}
