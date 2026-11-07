import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api } from "../api/client";
import type { AskAnswer } from "../api/types";
import { Page } from "../components/Page";
import { LineChart } from "../components/charts";
import { appName, money } from "../components/ui";
import { fmtMonthDay } from "../lib/dates";
import { useApp } from "../state";

const SUGGEST = [
  "How did we do tonight vs a usual Thursday?",
  "Why did we run out of chashu tonight?",
  "What's the forecast for tomorrow?",
  "Why was Oct 9 busy?",
  "Which past days were most like tomorrow?",
  "DoorDash sales last week?",
  "uber vs doordash last month",
  "How good has the forecast been lately?",
  "What was our best day this year?",
];

interface Msg { who: "you" | "gondola"; text: string; a?: AskAnswer }

export default function Ask() {
  const [msgs, setMsgs] = useState<Msg[]>([]);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const end = useRef<HTMLDivElement>(null);
  const { date, store } = useApp();
  const [sp, setSp] = useSearchParams();
  useEffect(() => { end.current?.scrollIntoView({ behavior: "smooth", block: "end" }); }, [msgs]);
  // questions handed over from a chart's "Ask about this"
  const pre = sp.get("q");
  useEffect(() => { if (pre) { send(pre); setSp({}, { replace: true }); } }, [pre]); // eslint-disable-line
  const send = async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    setMsgs((m) => [...m, { who: "you", text: t }]); setQ(""); setBusy(true);
    try { const a = await api.ask(t, date || undefined); setMsgs((m) => [...m, { who: "gondola", text: a.text, a }]); }
    catch (e) { setMsgs((m) => [...m, { who: "gondola", text: `Something went wrong: ${(e as Error).message}` }]); }
    finally { setBusy(false); }
  };
  const suggest = date && store && date !== store.today
    ? [`How did we do on ${fmtMonthDay(date)}?`, `Why was ${fmtMonthDay(date)} busy?`, ...SUGGEST.slice(2)]
    : SUGGEST;
  return (
    <Page title="Ask Gondola">
      <div style={{ display: "grid", gridTemplateColumns: "1fr 360px", gap: 22, alignItems: "start" }}>
        <div className="card" style={{ minHeight: 600, display: "flex", flexDirection: "column" }}>
          <div style={{ flex: 1, display: "flex", flexDirection: "column", gap: 14, paddingBottom: 14 }} aria-live="polite">
            {msgs.length === 0 && <div className="empty" style={{ marginTop: 80 }}> </div>}
            {msgs.map((m, i) => m.who === "you" ? (
              <div key={i} style={{ alignSelf: "flex-end", background: "var(--green)", color: "#fff", padding: "10px 16px", borderRadius: 18, maxWidth: "70%", fontSize: 15.5 }}>{m.text}</div>
            ) : (
              <div key={i} style={{ alignSelf: "flex-start", background: m.a?.clarify ? "var(--cream)" : "var(--bg)", padding: "14px 18px", borderRadius: 14, maxWidth: "86%", width: m.a?.chart ? "86%" : undefined }}>
                {m.a?.clarify && <div style={{ fontWeight: 600, fontSize: 13.5, color: "var(--ink2)", marginBottom: 4 }}>Asking what you mean</div>}
                <div style={{ fontSize: 15.5, lineHeight: 1.55 }}>{m.text}</div>
                {m.a?.chart && <div style={{ marginTop: 10, background: "#fff", borderRadius: 6, padding: 10 }}>
                  <ChartOf c={m.a.chart} />
                </div>}
                {m.a && m.a.calls.length > 0 && <div style={{ fontSize: 13, color: "var(--ink2)", marginTop: 8 }}>
                  Checked {m.a.calls.map(describeCall).join("; ")}
                </div>}
              </div>
            ))}
            {busy && <div className="typing" aria-label="Thinking"><i /><i /><i /></div>}
            <div ref={end} />
          </div>
          <form onSubmit={(e) => { e.preventDefault(); send(q); }} style={{ display: "flex", gap: 10 }}>
            <label htmlFor="ask" className="ink2" style={{ position: "absolute", left: -9999 }}>Question</label>
            <input id="ask" className="input" placeholder="Ask anything" value={q} onChange={(e) => setQ(e.target.value)} />
            <button className="btn" disabled={busy || !q.trim()}>Ask</button>
          </form>
        </div>
        <div className="card cream">
          <h3 style={{ marginBottom: 10 }}>Try</h3>
          {suggest.map((s) => (
            <button key={s} onClick={() => send(s)} disabled={busy} style={{ display: "block", textAlign: "left", width: "100%", padding: "9px 0", fontSize: 15, color: "var(--green)", fontWeight: 600 }}>{s}</button>
          ))}
        </div>
      </div>
    </Page>
  );
}

const NAMES: Record<string, string> = { net_sales: "Net sales", orders: "Orders", avg_ticket: "Average ticket", labour_pct: "Labour", cancels: "Cancels", avoidable_cancels: "Store-caused cancels" };

function ChartOf({ c }: { c: NonNullable<AskAnswer["chart"]> }) {
  const label = (v: string) => /^\d{4}-\d{2}-\d{2}$/.test(v)
    ? new Date(`${v}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : appName[v] || v;
  const isMoney = c.series.some((s) => /sales|ticket|amount|usd/.test(s.name));
  const isPct = c.series.every((s) => /pct|rate/.test(s.name));
  const fmt = (v: number) => (v === null || v === undefined || Number.isNaN(v) ? "" : isPct ? `${(v * 100).toFixed(1)}%` : isMoney ? money(v) : Math.round(v).toLocaleString());
  const series = c.series.map((s) => ({ ...s, name: NAMES[s.name] || appName[s.name] || s.name.replace(/_/g, " "), values: s.values.map((v) => Number(v) || 0) }));
  return <LineChart x={c.x.map(String).map(label)} series={series} kind={c.type} H={260} fmt={fmt} />;
}

function describeCall(c: unknown): string {
  if (!Array.isArray(c)) return String(c).replace(/_/g, " ");
  const [tool, ...args] = c.map((x) => (x === null || x === undefined ? "" : String(x)));
  const nice = (a: string) => /^\d{4}-\d{2}-\d{2}$/.test(a)
    ? new Date(`${a}T12:00:00`).toLocaleDateString("en-US", { month: "short", day: "numeric" })
    : appName[a] || NAMES[a] || a.replace(/_/g, " ");
  const rest = args.filter(Boolean).map(nice);
  const verb: Record<string, string> = { query_metric: "", compare_periods: "vs a usual day:", forecast: "forecast:", similar_days: "similar days:" };
  const head = tool in verb ? verb[tool] : tool.replace(/_/g, " ");
  return [head, rest.join(", ")].filter(Boolean).join(" ");
}
