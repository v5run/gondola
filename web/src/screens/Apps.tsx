/** Present › Apps: is each app taking orders, how full is the kitchen, and what Gondola suggests. */
import { useState } from "react";
import { tri } from "../api/tri";
import { Page } from "../components/Page";
import { CH_COLOR, ErrorBox, Skeleton } from "../components/ui";
import { StatusBar, chName, hm, usePresentState } from "../components/peak";
import { actionText } from "../live";
import { useToast } from "../state";

const APPS = ["doordash", "ubereats", "grubhub", "pickup", "dine_in"];
const RES: Record<string, string> = { noodles: "Noodle station", fryer: "Fryer", assembly: "Assembly", packing: "Packing", labour: "Cooks" };

export default function Apps() {
  const { st, error, retry, date, playback, closed, live } = usePresentState();
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const [tip, setTip] = useState<string | null>(null);
  const ask = async () => {
    setBusy(true); setTip(null);
    try {
      const r = await tri.present.agent(date);
      setTip(r.decision);
      for (const a of r.actions || []) live.push({ ...a, by: a.by || "rush-agent" });
    } catch (e) { toast(`Couldn't get a suggestion: ${(e as Error).message}`, "crit"); }
    finally { setBusy(false); }
  };
  const room = st?.headroom?.pct ?? st?.headroom_pct ?? null;
  const roomWord = room === null ? null : room > 20 ? "Plenty of room" : room >= 0 ? "Some room" : room >= -10 ? "Nearly full" : "Over capacity";
  const roomCls = room === null ? "" : room > 20 ? "ok" : room >= 0 ? "ok" : room >= -10 ? "tight" : "late";
  const changes = (st?.actions || []).filter((a) => a.action !== "ladder").slice(0, 6);
  return (
    <Page title="Present" date={false}>
      {error && <ErrorBox error={error} retry={retry} />}
      {!st && !error && <><Skeleton h={88} /><Skeleton h={300} /></>}
      {st && <>
        <StatusBar st={st} closed={closed} />
        <div className="ap-grid">
          {APPS.map((k) => {
            const s = st.channels?.[k] || (k === "pickup" || k === "dine_in" ? { state: "open" } : null);
            if (!s) return null;
            const word = s.state === "busy" ? "Paused" : s.state === "paused_items" ? "Some items paused" : s.state === "quoted" ? "Slowed" : "Open";
            const cls = s.state === "busy" ? "late" : s.state === "open" ? "ok" : "tight";
            const offer = (s as any).offer;
            return (
              <div key={k} className={`ap-card ${cls}`} style={{ ["--ch" as any]: CH_COLOR[k] || "#888" }}>
                <div className="ap-name">{chName(k)}</div>
                <div className="ap-state">{word}</div>
                <div className="ap-sub">
                  {s.state === "quoted" && `Quoting +${s.quoted_extra_min} min`}
                  {s.state === "paused_items" && (s.paused_items || []).join(", ")}
                  {s.state === "busy" && "Not taking new orders"}
                  {s.state === "open" && (offer ? `Deal on ${offer.item_name}` : k === "dine_in" || k === "pickup" ? "Never slowed by Gondola" : "Taking orders normally")}
                </div>
              </div>
            );
          })}
        </div>
        <div className="ap-row">
          <div className="card ap-room">
            <h3>Kitchen space, next 30 min</h3>
            {room === null ? <p className="ink2">Not available.</p> : <>
              <div className={`ap-big ${roomCls}`}>{roomWord}</div>
              <div className="ap-meter"><i className={roomCls} style={{ width: `${Math.max(3, Math.min(100, 50 + room))}%` }} /></div>
              {st.headroom?.binding && <p className="ink2">Tightest spot: <b>{RES[st.headroom.binding] || st.headroom.binding}</b></p>}
            </>}
          </div>
          <div className="card ap-tip">
            <h3>Suggestion</h3>
            {tip ? <p className="ap-tiptext">{tip}</p> : <p className="ink2">Ask Gondola whether to slow or pause anything on the delivery apps. Dine-in and pickup are never slowed.</p>}
            <button className="btn" onClick={ask} disabled={busy || closed || playback.active}>{busy ? "Thinking…" : tip ? "Ask again" : "Get a suggestion"}</button>
          </div>
        </div>
        <div className="card">
          <h3>Recent changes</h3>
          {changes.length === 0 ? <p className="ink2" style={{ marginTop: 6 }}>No changes yet today.</p> :
            <ul className="ap-log">{changes.map((a, i) => <li key={i}><span className="num">{hm(a.time || a.ts?.slice(11))}</span><span>{actionText(a)}</span></li>)}</ul>}
        </div>
      </>}
    </Page>
  );
}
