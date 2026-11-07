import { useEffect, useLayoutEffect, useRef, useState } from "react";
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
  "Why were orders late tonight?",
  "Why did we run out of chashu tonight?",
  "What's the forecast for tomorrow?",
  "Why was Oct 9 busy?",
  "Which past days were most like tomorrow?",
  "DoorDash sales last week?",
  "uber vs doordash last month",
  "How good has the forecast been lately?",
  "What was our best day this year?",
];

interface Msg { who: "you" | "gondola"; text: string; a?: AskAnswer; at?: number }
const KEY = "gondola.chat.v1";
const load = (): Msg[] => { try { const v = JSON.parse(localStorage.getItem(KEY) || "[]"); return Array.isArray(v) ? v : []; } catch { return []; } };

export default function Ask() {
  const [msgs, setMsgs] = useState<Msg[]>(load);
  const [q, setQ] = useState("");
  const [busy, setBusy] = useState(false);
  const [away, setAway] = useState(false); // the user scrolled up: don't yank them down
  const awayRef = useRef(false); awayRef.current = away;
  const list = useRef<HTMLDivElement>(null);
  const ta = useRef<HTMLTextAreaElement>(null);
  const { date, store } = useApp();
  const [sp, setSp] = useSearchParams();
  useEffect(() => { try { localStorage.setItem(KEY, JSON.stringify(msgs.slice(-80))); } catch { /* storage full */ } }, [msgs]);
  const toBottom = (smooth = true) => { const el = list.current; if (el) el.scrollTo({ top: el.scrollHeight, behavior: smooth ? "smooth" : "auto" }); };
  useLayoutEffect(() => { toBottom(false); }, []); // eslint-disable-line
  useEffect(() => { if (!away) toBottom(); }, [msgs.length, busy]); // eslint-disable-line
  // charts render after the text: keep the newest message in view as the list grows
  useEffect(() => {
    const el = list.current; if (!el) return;
    const ro = new ResizeObserver(() => { if (!awayRef.current) el.scrollTop = el.scrollHeight; });
    Array.from(el.children).forEach((c) => ro.observe(c));
    return () => ro.disconnect();
  }, [msgs.length]);
  const onScroll = () => { const el = list.current; if (!el) return; setAway(el.scrollHeight - el.scrollTop - el.clientHeight > 80); };
  const size = () => { const el = ta.current; if (!el) return; el.style.height = "auto"; el.style.height = `${Math.min(180, el.scrollHeight)}px`; };
  useLayoutEffect(size, [q]);
  // questions handed over from a chart's "Ask about this"
  const pre = sp.get("q");
  useEffect(() => { if (pre) { send(pre); setSp({}, { replace: true }); } }, [pre]); // eslint-disable-line
  const send = async (text: string) => {
    const t = text.trim();
    if (!t || busy) return;
    setAway(false);
    setMsgs((m) => [...m, { who: "you", text: t, at: Date.now() }]); setQ(""); setBusy(true);
    try { const a = await api.ask(t, date || undefined); setMsgs((m) => [...m, { who: "gondola", text: a.text, a, at: Date.now() }]); }
    catch (e) { setMsgs((m) => [...m, { who: "gondola", text: `Something went wrong: ${(e as Error).message}`, at: Date.now() }]); }
    finally { setBusy(false); ta.current?.focus(); }
  };
  const suggest = (date && store && date !== store.today
    ? [`How did we do on ${fmtMonthDay(date)}?`, `Why was ${fmtMonthDay(date)} busy?`, ...SUGGEST.slice(2)]
    : SUGGEST).slice(0, 6);
  const reset = () => { setMsgs([]); setAway(false); try { localStorage.removeItem(KEY); } catch { /* ignore */ } ta.current?.focus(); };
  return (
    <Page title="Ask Gondola" live={false} actions={<button className="btn light" onClick={reset} disabled={!msgs.length || busy}>New chat</button>}>
      <section className="chat" aria-label="Chat with Gondola">
        <div className="chat-list" ref={list} onScroll={onScroll} aria-live="polite" data-testid="chat-list">
          {msgs.length === 0 && !busy && <div className="chat-empty"><b>Ask about any night</b></div>}
          {msgs.map((m, i) => m.who === "you" ? (
            <div key={i} className="bub you">{m.text}</div>
          ) : (
            <div key={i} className={`bub bot${m.a?.clarify ? " clarify" : ""}${m.a?.chart ? " haschart" : ""}`}>
              {m.a?.clarify && <div style={{ fontWeight: 600, fontSize: 13.5, color: "var(--ink2)", marginBottom: 4 }}>Asking what you mean</div>}
              <div>{m.text}</div>
              {m.a?.chart && <div className="bchart"><ChartOf c={m.a.chart} /></div>}
              {m.a && m.a.calls.length > 0 && <div className="calls">Checked {m.a.calls.map(describeCall).join("; ")}</div>}
            </div>
          ))}
          {busy && <div className="bub bot typingb" aria-label="Gondola is typing"><div className="typing"><i /><i /><i /></div></div>}
        </div>
        {away && msgs.length > 0 && <button className="jump" style={{ bottom: msgs.length ? 92 : 140 }} onClick={() => { setAway(false); toBottom(); }}>Jump to latest</button>}
        <div className="chat-foot">
          {msgs.length === 0 && <div className="chips" aria-label="Suggested questions">
            {suggest.map((s) => <button key={s} onClick={() => send(s)} disabled={busy}>{s}</button>)}
          </div>}
          <form className="chat-input" onSubmit={(e) => { e.preventDefault(); send(q); }}>
            <label htmlFor="ask" style={{ position: "absolute", left: -9999 }}>Question</label>
            <textarea id="ask" ref={ta} rows={1} placeholder="Ask anything" value={q} onChange={(e) => setQ(e.target.value)}
              onKeyDown={(e) => { if (e.key === "Enter" && !e.shiftKey && !e.nativeEvent.isComposing) { e.preventDefault(); send(q); } }} />
            <button className="btn" disabled={busy || !q.trim()}>Send</button>
          </form>
        </div>
      </section>
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
  const rest = args.filter((x) => x && x !== "None" && x !== "null").map(nice);
  const verb: Record<string, string> = { query_metric: "", compare_periods: "vs a usual day:", forecast: "forecast:", similar_days: "similar days:" };
  const head = tool in verb ? verb[tool] : tool.replace(/_/g, " ");
  return [head, rest.join(", ")].filter(Boolean).join(" ");
}
