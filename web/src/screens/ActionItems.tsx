import { useEffect, useState } from "react";
import { outcomeText, tri, type ActionItem } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { Status, measureText } from "../components/review";
import { ErrorBox, Segmented, SkeletonCard, shortDate } from "../components/ui";
import { useApp, useToast } from "../state";
import { Own, useAgents } from "../agents";

const FILTERS: [string, string][] = [["open", "Open"], ["done", "Done"], ["not_working", "Not working"], ["", "All"]];

export default function ActionItems() {
  const { now } = useApp();
  const toast = useToast();
  const { pulse } = useAgents();
  const [f, setF] = useState("open");
  const [list, setList] = useState<ActionItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  const [busy, setBusy] = useState<string | null>(null);
  useEffect(() => {
    let on = true;
    setErr(null);
    tri.review.actions(f || undefined).then((l) => on && setList(l)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [f, n]);
  const today = now?.today || "";
  const set = async (a: ActionItem, s: "done" | "not_working" | "open") => {
    setBusy(a.id);
    try { await tri.review.setAction(a.id, s); pulse("review", `${a.text.replace(/^./, (c) => c.toLowerCase())}: ${s.replace("_", " ")}`); toast("Updated", "good"); setN((x) => x + 1); }
    catch (e) { toast(`Couldn't update: ${(e as Error).message}`, "crit"); }
    finally { setBusy(null); }
  };
  return (
    <Page title="Review" date={false} live={false}>
      {err && <ErrorBox error={err} retry={() => setN((x) => x + 1)} />}
      {!list && !err && <SkeletonCard h={260} lines={6} />}
      {list && <div className="card"><Own a="review" /><Info k="action_items" />
        <div className="cardhead"><h3>Action items</h3><Segmented label="Status" value={f} onChange={setF} options={FILTERS} /></div>
        {list.length === 0 && <div className="empty">None</div>}
        {list.length > 0 && <div className="tblwrap"><table className="tbl" data-testid="action-items">
          <thead><tr><th>Action</th><th>Owner</th><th>Check</th><th>Measure</th><th>Status</th><th /></tr></thead>
          <tbody>
            {list.map((a) => {
              const due = a.status === "open" && a.check_on && today && a.check_on <= today;
              const out = outcomeText(a.outcome);
              return (
                <tr key={a.id} data-id={a.id}>
                  <td style={{ minWidth: 260 }}><b style={{ fontWeight: 600 }}>{a.text}</b>{out && <div className="ink2" style={{ fontSize: 13.5 }}>{out}</div>}</td>
                  <td>{a.owner || "–"}</td>
                  <td className={due ? "crit" : undefined} style={{ whiteSpace: "nowrap" }}>{a.check_on ? shortDate(a.check_on) : "–"}{due ? " · due" : ""}</td>
                  <td className="ink2" style={{ minWidth: 180 }}>{measureText(a.measure) || "–"}</td>
                  <td><Status s={a.status} /></td>
                  <td className="r" style={{ whiteSpace: "nowrap" }}>
                    {a.status === "open" ? <>
                      <button className="link" onClick={() => set(a, "done")} disabled={busy === a.id}>Worked</button>
                      <button className="link" style={{ marginLeft: 14 }} onClick={() => set(a, "not_working")} disabled={busy === a.id}>Didn't</button>
                    </> : <button className="link" onClick={() => set(a, "open")} disabled={busy === a.id}>Reopen</button>}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table></div>}
      </div>}
    </Page>
  );
}
