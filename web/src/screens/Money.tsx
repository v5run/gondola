import { useState } from "react";
import { api } from "../api/client";
import type { Dispute, PayoutChannel } from "../api/types";
import { Page } from "../components/Page";
import { HBar } from "../components/charts";
import { CH_COLOR, Drawer, ErrorBox, Skeleton, SkeletonCard, Tween, appName, money, shortDate, useLoad } from "../components/ui";
import { fmtMonthDay } from "../lib/dates";
import { useApp, useToast } from "../state";
import { Own } from "../agents";

const APPS = ["doordash", "ubereats", "grubhub"];
const SHORT_REASON: Record<string, string> = {
  "charge is more than any single item on the order": "Higher than any item",
  "charge equals the price of a menu item that wasn't on the order": "Item not on the order",
};
const dayOf = (d: Dispute) => d.date || (d as Dispute & { for_date?: string }).for_date;
const evidence = (d: Dispute) => {
  const day = dayOf(d);
  return `${appName[d.channel] || d.channel} order ${d.order}${day ? ` (${day})` : ""}: error charge of $${d.amount.toFixed(2)}.${d.items?.length ? ` Items on the order: ${d.items.join(", ")}.` : ""} Reason: ${d.reason}.`;
};

export default function Money() {
  const { date } = useApp();
  const cl = useLoad(() => (date ? api.close(date).catch((e) => (/no close/i.test(String(e.message)) ? null : Promise.reject(e))) : new Promise<never>(() => {})), [date]);
  const [allDisputes, setAllDisputes] = useState(false);
  const [app, setApp] = useState("doordash");
  const [sel, setSel] = useState<Dispute | null>(null);
  const d = cl.data && cl.data.date === date ? cl.data : null;
  const cash = d?.books.cash;
  const verified = [...(d?.books.verified || [])].sort((a, b) => a.date.localeCompare(b.date));
  const open = (d?.disputes || []).filter((x) => x.days_left >= 0 && x.days_left < 14).sort((a, b) => a.days_left - b.days_left || b.amount - a.amount);
  const shown = allDisputes ? open : open.slice(0, 8);
  const recoverable = open.reduce((a, x) => a + x.amount, 0);
  const tonightTotal = (d?.books.estimate_today || []).reduce((a, c) => a + (c.expected || 0), 0);
  const rowsFor = (a: string) => verified.map((v) => ({ date: v.date, c: v.channels.find((c) => c.channel === a) })).filter((r) => r.c) as { date: string; c: PayoutChannel }[];
  const shortOf = (a: string) => rowsFor(a).reduce((s, r) => s + Math.min(0, r.c.difference ?? 0), 0);
  const maxShort = Math.max(1, ...APPS.map((a) => -shortOf(a)));
  return (
    <Page title="Money">
      {cl.error && <ErrorBox error={cl.error} retry={cl.reload} />}
      {cl.loading && <div className="grid3">{[0, 1, 2].map((i) => <SkeletonCard key={i} h={130} lines={1} />)}</div>}
      {!cl.loading && !d && !cl.error && <div className="card empty">No close for {fmtMonthDay(date)}</div>}
      {d && <>
        <div className="grid3">
          <div className="card kpi" style={{ background: "var(--ink)", color: "#fff" }}>
            <Own a="books" dark /><div className="l" style={{ color: "#cfd6d2" }}>Cash drawer</div>
            <div className="v" style={{ color: (cash?.difference ?? 0) < -5 ? "#f2a29d" : "var(--mint)" }}>{cash?.difference === null || cash?.difference === undefined ? "Not counted" : <Tween value={cash.difference} fmt={(v) => money(v, 2)} />}</div>
            <div style={{ color: "#cfd6d2", fontSize: 14 }} className="num">{cash?.expected === undefined ? "" : `Expected ${money(cash.expected, 2)}${cash.counted == null ? "" : ` · counted ${money(cash.counted, 2)}`}`}</div>
          </div>
          <div className="card kpi cream">
            <Own a="books" /><div className="l">Recoverable</div>
            <div className="v"><Tween value={recoverable} fmt={(v) => money(v, 2)} /></div>
            <div className="ink2 num" style={{ fontSize: 14 }}>{open.length} charges · {open.filter((x) => x.days_left <= 3).length} closing within 3 days</div>
          </div>
          <div className="card kpi">
            <Own a="books" /><div className="l">App payouts, estimated</div>
            <div className="v"><Tween value={tonightTotal} fmt={(v) => money(v)} /></div>
            <div className="ink2 num" style={{ fontSize: 14 }}>{(d.books.estimate_today || []).map((c) => `${appName[c.channel]} ${money(c.expected)}`).join(" · ")}</div>
          </div>
        </div>

        <div style={{ display: "grid", gridTemplateColumns: "1fr 1.35fr", gap: 22, alignItems: "start" }}>
          <div className="card">
            <Own a="books" /><div className="cardhead"><h3>Payouts</h3></div>
            {APPS.map((a) => {
              const s = shortOf(a);
              return (
                <button key={a} className={`clickrow${app === a ? " on" : ""}`} onClick={() => setApp(a)} aria-pressed={app === a}>
                  <span style={{ width: 100, fontWeight: 600 }}><i className="sw" style={{ background: CH_COLOR[a] }} />{appName[a]}</span>
                  <span style={{ flex: 1 }}><HBar value={-s} max={maxShort} color="#d03b3b" track={app === a ? "#a7dc71" : "#ecebe5"} /></span>
                  <b className={`num${s < -1 ? " crit" : ""}`} style={{ minWidth: 84, textAlign: "right" }}>{s < -1 ? money(s, 2) : "Paid"}</b>
                </button>
              );
            })}
            <AppRows key={app} rows={rowsFor(app)} tonight={d.books.estimate_today.find((c) => c.channel === app)} />
          </div>

          <div className="card">
            <Own a="books" /><div className="cardhead"><h3>Dispute checklist</h3><span className="ink2 num" style={{ fontSize: 14 }}>{open.length}</span></div>
            {open.length === 0 ? <div className="empty">Nothing to dispute</div> : <>
              <table className="tbl">
                <thead><tr><th>App</th><th>Order</th><th>Reason</th><th className="r">Charge</th><th className="r">Days left</th><th /></tr></thead>
                <tbody>{shown.map((x) => <DisputeRow key={`${x.channel}-${x.order}`} d={x} onOpen={() => setSel(x)} />)}</tbody>
              </table>
              {open.length > 8 && (
                <button className="link" style={{ marginTop: 10 }} onClick={() => setAllDisputes((v) => !v)}>
                  {allDisputes ? "Show the 8 closing soonest" : `Show all ${open.length}`}
                </button>
              )}
            </>}
          </div>
        </div>
      </>}
      {!d && cl.loading && <Skeleton h={300} />}
      <DisputeDrawer d={sel} onClose={() => setSel(null)} />
    </Page>
  );
}

function AppRows({ rows, tonight }: { rows: { date: string; c: PayoutChannel }[]; tonight?: PayoutChannel }) {
  return (
    <div className="approws" data-testid="payout-rows">
      <div className="approw head ink2"><span>Day</span><span>Orders</span><span>Expected</span><span>Paid</span><span>Difference</span></div>
      {tonight && <div className="approw enter"><span>Tonight</span><span>{tonight.orders}</span><span>{money(tonight.expected, 2)}</span><span className="ink2">Pending</span><span className="ink2">–</span></div>}
      {[...rows].reverse().map(({ date, c }, i) => (
        <div key={date} className="approw enter" style={{ animationDelay: `${Math.min(i, 10) * 18}ms` }}>
          <span>{shortDate(date)}</span><span>{c.orders}</span><span>{money(c.expected, 2)}</span><span>{c.reported == null ? "Pending" : money(c.reported, 2)}</span>
          <b className={c.difference !== null && c.difference < -1 ? "crit" : ""}>{c.difference === null ? "–" : Math.abs(c.difference) < 0.005 ? "$0.00" : money(c.difference, 2)}</b>
        </div>
      ))}
    </div>
  );
}

function DisputeRow({ d, onOpen }: { d: Dispute; onOpen: () => void }) {
  const toast = useToast();
  const [copied, setCopied] = useState(false);
  const day = dayOf(d);
  const copy = async (e: React.MouseEvent) => {
    e.stopPropagation();
    try { await navigator.clipboard.writeText(evidence(d)); setCopied(true); toast(`Evidence for ${d.order} copied`, "good"); setTimeout(() => setCopied(false), 1600); } catch { /* clipboard blocked */ }
  };
  const reason = SHORT_REASON[d.reason] || d.reason.charAt(0).toUpperCase() + d.reason.slice(1);
  return (
    <tr className="rowlink" onClick={onOpen} tabIndex={0} onKeyDown={(e) => e.key === "Enter" && onOpen()}>
      <td style={{ fontWeight: 600 }}>{appName[d.channel] || d.channel}</td>
      <td className="num">{d.order}{day && <div className="ink2" style={{ fontSize: 13 }}>{shortDate(day)}</div>}</td>
      <td style={{ fontSize: 14 }}>{reason}</td>
      <td className="r" style={{ fontWeight: 600 }}>{money(d.amount, 2)}</td>
      <td className={`r${d.days_left <= 3 ? " crit" : ""}`} style={{ fontWeight: 600 }}>{d.days_left === 0 ? "Today" : d.days_left}</td>
      <td className="r"><button className="btn light small" style={{ background: "var(--paper)" }} onClick={copy} aria-label={`Copy evidence for ${d.order}`}>{copied ? "Copied" : "Copy"}</button></td>
    </tr>
  );
}

function DisputeDrawer({ d, onClose }: { d: Dispute | null; onClose: () => void }) {
  const toast = useToast();
  const copy = async () => { if (!d) return; try { await navigator.clipboard.writeText(evidence(d)); toast("Evidence copied", "good"); } catch { /* blocked */ } };
  return (
    <Drawer open={!!d} onClose={onClose} label="Dispute" width={480}>
      {d && <>
        <h2>{appName[d.channel]} · {d.order}</h2>
        <div className="grid2" style={{ gap: 12 }}>
          <div className="card kpi"><div className="l">Charge</div><div className="v">{money(d.amount, 2)}</div></div>
          <div className="card kpi"><div className="l">Days left</div><div className={`v${d.days_left <= 3 ? " crit" : ""}`}>{d.days_left === 0 ? "Today" : d.days_left}</div></div>
        </div>
        <div className="card">
          <dl className="facts">
            <dt>Order date</dt><dd>{dayOf(d) ? shortDate(dayOf(d)!) : "–"}</dd>
            <dt>Reason</dt><dd style={{ textAlign: "right", maxWidth: 260 }}>{SHORT_REASON[d.reason] || d.reason}</dd>
            {d.items?.length ? <><dt>Items</dt><dd>{d.items.join(", ")}</dd></> : null}
          </dl>
        </div>
        <div className="card cream evidence" data-testid="evidence">{evidence(d)}</div>
        <div><button className="btn" onClick={copy}>Copy evidence</button></div>
      </>}
    </Drawer>
  );
}
