import { useEffect, useMemo, useState } from "react";
import { tri, type PresentSettings, type PresentState } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { ActionList, ComparePanel, DEFAULT_SETTINGS, KitchenTimeline, LadderHero, QueueBoard, SettingsDrawer, useChannelOf, useCompare } from "../components/present";
import { ErrorBox, Icon, Skeleton, SkeletonCard } from "../components/ui";
import { toMin } from "../lib/dates";
import { useApp, useClock, useToast } from "../state";
import { usePlayback } from "../playback";
import { usePresentLive } from "../live";
import { Own, useAgents } from "../agents";

export default function Queue() {
  const { date, now, inService } = useApp();
  const live = usePresentLive();
  const playback = usePlayback();
  const clockNow = useClock();
  const toast = useToast();
  const { pulse, setRunning } = useAgents();
  const isToday = !!now && date === now.today;
  // today comes from the live stream; other days are read once
  const [other, setOther] = useState<PresentState | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!date || isToday || playback.active) return;
    let on = true;
    setOther(null); setErr(null);
    tri.present.state(date).then((s) => on && setOther(s)).catch((e) => on && setErr(String(e.message)));
    return () => { on = false; };
  }, [date, isToday, n, playback.active]);
  const st = playback.active ? playback.frame?.present ?? null : isToday ? live.state : other && other.date === date ? other : null;
  const error = playback.active ? null : isToday ? (live.status === "error" && !st ? live.error : null) : err;
  const [settings, setSettings] = useState<PresentSettings>(DEFAULT_SETTINGS);
  useEffect(() => { tri.present.settings().then(setSettings).catch(() => {}); }, []);
  const [drawer, setDrawer] = useState(false);
  const [sel, setSel] = useState<string | null>(null);
  const [hover, setHover] = useState<string | null>(null);
  const [agentBusy, setAgentBusy] = useState(false);
  const [receipt, setReceipt] = useState<{ decision: string; id?: string; model?: string } | null>(null);
  const cmp = useCompare(playback.active ? "" : date, isToday && inService && !playback.active);
  const chOf = useChannelOf(st?.queue || []);

  // real time between updates: minutes since the state's clock
  const liveNow = !playback.active && isToday && inService && !!st && !!clockNow;
  const stMin = st ? toMin(st.now) : 0;
  const nowMin = playback.active ? playback.minute : liveNow ? Math.max(stMin, toMin(clockNow!)) : stMin;
  const elapsed = liveNow ? Math.min(3, Math.max(0, nowMin - stMin)) : 0;
  const closed = !!st && st.phase === "closed";
  useEffect(() => { if (sel && st && !st.queue.some((r) => r.order_id === sel)) setSel(null); }, [st, sel]);
  const late = useMemo(() => (st ? st.queue.filter((r) => r.status === "queued" && r.slack_min !== null && r.slack_min - elapsed < 0).length : 0), [st, elapsed]);

  const runAgent = async () => {
    setAgentBusy(true); setRunning("rush", true); setReceipt(null);
    try {
      const r = await tri.present.agent(date);
      const rc = typeof r.receipt === "string" ? { receipt_id: r.receipt } : r.receipt || {};
      setReceipt({ decision: r.decision, id: rc.receipt_id || rc.id, model: rc.model });
      for (const a of r.actions || []) live.push({ ...a, by: a.by || "rush-agent" });
      pulse("rush", r.decision.replace(/^./, (c) => c.toLowerCase()));
      toast(`Rush agent: ${r.decision}`, "good");
    } catch (e) { toast(`Rush agent: ${(e as Error).message}`, "crit"); }
    finally { setAgentBusy(false); setRunning("rush", false); }
  };

  const actions = playback.active ? null : <>
    <button className="iconbtn" onClick={() => setDrawer(true)} aria-label="Ladder settings" title="Ladder settings"><Icon name="gear" size={20} /></button>
    <button className="btn" onClick={runAgent} disabled={agentBusy || !st || closed} data-testid="run-agent">{agentBusy ? "Rush agent working" : "Run Rush agent"}</button>
  </>;

  return (
    <Page title="Present" actions={actions}>
      {error && <ErrorBox error={error} retry={() => (isToday ? live.refresh() : setN((x) => x + 1))} />}
      {!st && !error && <><Skeleton h={190} /><div className="present-grid"><SkeletonCard h={420} lines={8} /><SkeletonCard h={420} /></div></>}
      {st && <>
        <LadderHero st={st} settings={settings} date={date} onSettings={playback.active ? undefined : () => setDrawer(true)} />
        <div className="present-grid">
          <div className="card qcard"><Own a="controller" /><Info k="queue" />
            <div className="cardhead">
              <h3>Queue</h3>
              <span className="ink2 num qsum">{st.queue.length} open{late ? <span className="crit"> · {late} behind</span> : null}</span>
            </div>
            <QueueBoard rows={st.queue} elapsed={elapsed} sel={sel} setSel={setSel} hover={hover} setHover={setHover} fresh={playback.active ? new Set() : live.fresh} closed={closed} />
          </div>
          <div className="present-side">
            <div className="card"><Own a="ledger" /><Info k="compare" />
              <div className="cardhead"><h3>Gondola vs first-come</h3></div>
              <ComparePanel c={(playback.active ? st.compare : cmp || st.compare) || null} n={playback.active ? undefined : cmp?.orders} />
            </div>
            <div className="card"><Own a="rush" /><Info k="actions" />
              <div className="cardhead"><h3>Actions</h3></div>
              {receipt && !playback.active && <div className="receipt enter" data-testid="agent-receipt"><b>{receipt.decision}</b><span className="ink2">{[receipt.id && `Receipt ${receipt.id}`, receipt.model].filter(Boolean).join(" · ")}</span></div>}
              <ActionList actions={st.actions} max={receipt ? 5 : 6} />
            </div>
          </div>
        </div>
        <div className="card"><Own a="controller" /><Info k="kitchen_timeline" />
          <div className="cardhead"><h3>Kitchen</h3></div>
          <KitchenTimeline stations={st.stations} nowMin={nowMin} chOf={chOf} hover={hover} setHover={setHover}
            onPick={(id) => { setSel(id); document.querySelector(`[data-order="${id}"]`)?.scrollIntoView({ block: "nearest", behavior: "smooth" }); }} />
        </div>
      </>}
      <SettingsDrawer open={drawer && !playback.active} onClose={() => setDrawer(false)} onSaved={(s) => { setSettings(s); toast("Ladder settings saved", "good"); pulse("controller", "new thresholds applied"); live.refresh(); setN((x) => x + 1); }} />
    </Page>
  );
}
