import { useEffect, useRef, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "../api/client";
import type { OutboxMsg } from "../api/types";
import { Page } from "../components/Page";
import { ErrorBox, Logo, money, useLoad } from "../components/ui";
import { addDays, fmtMonthDay } from "../lib/dates";
import { useApp } from "../state";
import { Own } from "../agents";

const QUICK = ["1", "2", "3", "why did we run out of chashu?", "approve tomorrow's plan"];

export default function Alerts() {
  const { date } = useApp();
  const ob = useLoad(() => api.outbox(), []);
  const ov = useLoad(() => (date ? api.overview(date) : new Promise<never>(() => {})), [date]);
  // messages belong to the night they were sent (replies after midnight still count)
  const onNight = (m: OutboxMsg) => { const d = m.ts.slice(0, 10); return d === date || (d === addDays(date, 1) && Number(m.ts.slice(11, 13)) < 6); };
  const [extra, setExtra] = useState<OutboxMsg[]>([]);
  const [text, setText] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const night = (ob.data || []).filter(onNight);
  const all = [...night].reverse().concat(extra);
  const sms = all.filter((m) => m.channel === "sms");
  const email = night.find((m) => m.channel === "email");
  useEffect(() => { end.current?.scrollIntoView({ block: "end" }); }, [sms.length]);
  const send = async (body: string) => {
    const b = body.trim();
    if (!b || busy) return;
    setBusy(true); setText("");
    const now = new Date().toISOString();
    setExtra((x) => [...x, { channel: "sms", body: b, ts: now, from: "manager" }]);
    try {
      const reply = await api.smsInbound(b);
      setExtra((x) => [...x, { channel: "sms", body: reply, ts: new Date().toISOString(), from: "gondola" }]);
    } catch (e) {
      setExtra((x) => [...x, { channel: "sms", body: `Couldn't reach Gondola: ${(e as Error).message}`, ts: now, from: "gondola" }]);
    } finally { setBusy(false); }
  };
  const reportDate = email?.attachment?.match(/(\d{4}-\d{2}-\d{2})/)?.[1] || email?.ts.slice(0, 10) || date;
  const fromManager = (m: OutboxMsg) => m.from === "manager" || m.direction === "in" || m.status === "received";
  return (
    <Page title="Alerts">
      {ob.error && <ErrorBox error={ob.error} retry={ob.reload} />}
      <div style={{ display: "grid", gridTemplateColumns: "400px 1fr", gap: 40, alignItems: "start" }}>
        <div style={{ width: 380, height: 760, borderRadius: 42, background: "var(--ink)", padding: 12 }}>
          <div style={{ width: "100%", height: "100%", borderRadius: 32, background: "#fff", display: "flex", flexDirection: "column", overflow: "hidden" }}>
            <div style={{ display: "flex", justifyContent: "space-between", padding: "12px 26px 0", fontSize: 13, fontWeight: 600 }}><span>11:06</span><span>5G</span></div>
            <div style={{ display: "flex", flexDirection: "column", alignItems: "center", padding: "10px 0 8px" }}>
              <Logo size={44} /><div style={{ fontWeight: 700, marginTop: 4 }}>Gondola</div>
            </div>
            <div style={{ flex: 1, overflowY: "auto", padding: "4px 14px", display: "flex", flexDirection: "column", gap: 10 }} aria-live="polite">
              {sms.length === 0 && <div className="ink2" style={{ textAlign: "center", marginTop: 40, fontSize: 14 }}>No texts on {fmtMonthDay(date)}</div>}
              {sms.map((m, i) => (
                <div key={i} style={{
                  alignSelf: fromManager(m) ? "flex-end" : "flex-start", maxWidth: "82%", padding: "10px 14px", borderRadius: 18, fontSize: 14.5, lineHeight: 1.45,
                  background: fromManager(m) ? "var(--green)" : "#ecebe5", color: fromManager(m) ? "#fff" : "var(--ink)",
                }}>{m.body}</div>
              ))}
              {busy && <div className="ink2" style={{ fontSize: 13 }}>Gondola is typing</div>}
              <div ref={end} />
            </div>
            <form onSubmit={(e) => { e.preventDefault(); send(text); }} style={{ display: "flex", gap: 8, padding: 12 }}>
              <input className="input" style={{ borderRadius: 20, fontSize: 14.5 }} placeholder="Text Gondola" aria-label="Reply" value={text} onChange={(e) => setText(e.target.value)} />
              <button className="btn small" style={{ borderRadius: 20 }} disabled={busy || !text.trim()}>Send</button>
            </form>
          </div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div className="card">
            <Own a="sentinel" /><h3 style={{ marginBottom: 12 }}>Quick replies</h3>
            <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
              {QUICK.map((q) => <button key={q} className="btn light small" style={{ background: "var(--bg)" }} onClick={() => send(q)} disabled={busy}>{q}</button>)}
            </div>
          </div>
          {email && (
            <div className="card" style={{ padding: "26px 30px" }}>
              <div style={{ display: "flex", gap: 14, alignItems: "center" }}>
                <Logo size={46} />
                <div><div style={{ fontWeight: 700, fontSize: 17 }}>Gondola</div><div className="ink2" style={{ fontSize: 14 }}>to {Array.isArray(email.to) ? email.to.join(", ") : email.to} · {new Date(email.ts).toLocaleTimeString("en-US", { hour: "numeric", minute: "2-digit" })}</div></div>
              </div>
              <h2 style={{ fontSize: 24, margin: "16px 0 12px" }}>{email.subject}</h2>
              {ov.data?.kpis && <div style={{ background: "var(--green)", color: "#fff", borderRadius: 6, padding: "16px 22px", display: "grid", gridTemplateColumns: "repeat(3,1fr)" }}>
                <div><div style={{ color: "var(--onGreen)", fontSize: 14 }}>Net sales</div><div className="num" style={{ fontSize: 30, fontWeight: 700 }}>{money(ov.data.kpis.net_sales)}</div></div>
                <div><div style={{ color: "var(--onGreen)", fontSize: 14 }}>Orders</div><div className="num" style={{ fontSize: 30, fontWeight: 700 }}>{ov.data.kpis.orders}</div></div>
                <div><div style={{ color: "var(--onGreen)", fontSize: 14 }}>Status</div><div style={{ fontSize: 30, fontWeight: 700 }}>{email.status === "sent" ? "Sent" : "Demo"}</div></div>
              </div>}
              <p style={{ fontSize: 16, lineHeight: 1.6, margin: "14px 0" }}>{email.body}</p>
              {email.attachment && reportDate && <a href={`/api/reports/${reportDate}.pdf`} target="_blank" rel="noreferrer" style={{ display: "flex", gap: 14, alignItems: "center", background: "var(--bg)", borderRadius: 6, padding: "12px 16px", textDecoration: "none" }}>
                <div style={{ width: 40, height: 50, background: "var(--crit)", borderRadius: 3 }} />
                <div><div style={{ fontWeight: 700 }}>Daily Close Report · {reportDate}.pdf</div><div className="ink2" style={{ fontSize: 14 }}>2 pages</div></div>
              </a>}
              <Link className="btn" to="/future/tomorrow" style={{ display: "inline-block", marginTop: 16, textDecoration: "none" }}>Approve tomorrow's plan</Link>
            </div>
          )}
        </div>
      </div>
    </Page>
  );
}
