import { useEffect, useRef, useState } from "react";
import { api, stream } from "../api/client";
import type { Channel, GuardDone, GuardTick } from "../api/types";
import { Page } from "../components/Page";
import { HBar } from "../components/charts";
import { CH_COLOR, FoodIcon, Icon, NumberField, Tween, appName, clock, useLoad } from "../components/ui";
import { fmtMonthDay, fromMin, toMin } from "../lib/dates";
import { useApp, useToast } from "../state";
import { Own, useAgents } from "../agents";

const CHANNELS: Channel[] = ["in_store", "doordash", "ubereats", "grubhub"];
const MENU = [["Tonkotsu", "19.25"], ["Spicy Miso", "19.25"], ["Shoyu", "18.15"], ["Chashu Don", "15.40"], ["Chashu Bao", "9.35"]];

interface Ev { t: string; text: string; kind: "pause" | "recount" | "info" | "sold" }

export default function Service() {
  const { date, speed } = useApp();
  const toast = useToast();
  const { pulse } = useAgents();
  const [run, setRun] = useState<string | null>(null);
  const [ticks, setTicks] = useState<GuardTick[]>([]);
  const [head, setHead] = useState(0);
  const [follow, setFollow] = useState(true);
  const [playing, setPlaying] = useState(true);
  const [events, setEvents] = useState<Ev[]>([]);
  const [prompt, setPrompt] = useState<{ believed_left: number; t?: string } | null>(null);
  const [count, setCount] = useState(0);
  const [done, setDone] = useState<GuardDone | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [par, setPar] = useState<number | null>(null);
  const [span, setSpan] = useState<[number, number]>([17 * 60, 22 * 60 + 30]);
  const ov = useLoad(() => (date ? api.overview(date) : new Promise<never>(() => {})), [date]);
  const stopRef = useRef<() => void>(() => {});
  useEffect(() => () => stopRef.current(), []);
  // a new date resets the replay
  useEffect(() => { stopRef.current(); setRun(null); setTicks([]); setEvents([]); setDone(null); setPar(null); setPrompt(null); setErr(null); }, [date]);

  const addEv = (e: Ev) => setEvents((x) => [...x, e]);
  const start = async () => {
    stopRef.current();
    setTicks([]); setHead(0); setFollow(true); setPlaying(true); setEvents([]); setPrompt(null); setDone(null); setErr(null); setPar(null);
    try {
      const r = await api.guardReplay({ date, speed, count_error: 0.06, recount: true, start_time: "17:00" });
      setRun(r.run_id);
      stopRef.current = stream(`/guard/${encodeURIComponent(r.run_id)}/events`, {
        start: (st: { par?: number; start_time?: string; close?: string }) => {
          setPar(typeof st.par === "number" ? st.par : null);
          setSpan([toMin(st.start_time || "17:00"), toMin(st.close || "22:30")]);
        },
        tick: (t: GuardTick) => setTicks((x) => [...x, t]),
        recount_done: (r: { t?: string; count?: number; source?: string }) => {
          setPrompt(null);
          if (r.source && r.source !== "manager" && typeof r.count === "number") addEv({ t: r.t || "", text: `No reply · line count ${r.count}`, kind: "recount" });
        },
        sold_out: (o: { t?: string }) => { addEv({ t: o.t || "", text: "Chashu ran out", kind: "sold" }); toast("Chashu ran out in the kitchen", "crit"); },
        recount_prompt: (p: { believed_left: number; t?: string }) => {
          setPrompt(p); setCount(p.believed_left); pulse("guard", `asked for a recount at ${p.believed_left}`, p.t);
          addEv({ t: p.t || "", text: `Recount asked at ${p.believed_left}`, kind: "recount" });
        },
        pause: (p: { app: string; t: string }) => { addEv({ t: p.t, text: `Paused on ${appName[p.app]}`, kind: "pause" }); toast(`Chashu paused on ${appName[p.app]}`, "crit"); pulse("guard", `paused chashu on ${appName[p.app]}`, p.t); },
        done: (d: GuardDone & { status?: string; error?: string }) => {
          if (d.status === "failed") setErr(d.error || "The replay stopped early"); else setDone(d);
          setRun(null); setPrompt(null);
        },
        error: (e: { message: string }) => setErr(e.message),
      });
    } catch (e) { setErr(String((e as Error).message)); }
  };
  const stop = () => { stopRef.current(); setRun(null); };
  const answer = async () => {
    const n = Math.max(0, count);
    setPrompt(null);
    addEv({ t: ticks[ticks.length - 1]?.t || "", text: `Line counted ${n}`, kind: "info" });
    try { if (run) await api.guardRecount(run, n); } catch { /* replay may have finished */ }
  };

  // playback head: follows the stream, or plays the buffer forward from where you scrubbed
  const last = ticks.length - 1;
  const shown = follow ? last : Math.min(head, last);
  useEffect(() => {
    if (follow || !playing || shown >= last) { if (!follow && playing && shown >= last && last >= 0) setFollow(true); return; }
    const id = setInterval(() => setHead((h) => Math.min(h + 1, last)), Math.max(30, 60000 / speed));
    return () => clearInterval(id);
  }, [follow, playing, shown, last, speed]);
  const tick = shown >= 0 ? ticks[shown] : null;
  const atT = tick ? toMin(tick.t) : null;
  const seen = events.filter((e) => !e.t || atT === null || toMin(e.t) <= atT);
  const maxSold = tick ? Math.max(1, ...Object.values(tick.sold)) : 1;
  const scrubTo = (m: number) => {
    if (!ticks.length) return;
    let i = ticks.findIndex((t) => toMin(t.t) >= m);
    if (i < 0) i = last;
    setFollow(false); setPlaying(false); setHead(i);
  };
  const live = !!run && follow;

  const actions = <>
    {run ? <button className="btn" onClick={stop}>Stop</button> : <button className="btn" onClick={start} disabled={!date}>{done ? "Replay again" : "Start service"}</button>}
  </>;
  return (
    <Page title="Service" actions={actions}>
      {err && <div className="error">{err}</div>}
      <div className="card scrub">
        <button className="iconbtn" aria-label={playing && (follow || shown < last) ? "Pause" : "Play"} disabled={!ticks.length}
          onClick={() => { if (playing) { setPlaying(false); setHead(shown); setFollow(false); } else { setPlaying(true); if (shown >= last) setFollow(true); } }}>
          <Icon name={playing ? "pause" : "play"} size={18} />
        </button>
        <span className="num scrub-t">{tick ? clock(tick.t) : clock(fromMin(span[0]))}</span>
        <Scrubber span={span} buffered={ticks.length ? toMin(ticks[last].t) : span[0]} at={atT ?? span[0]} events={events} onSeek={scrubTo} />
        <button className={`btn small ${live ? "mint" : "light"}`} disabled={!run || follow} onClick={() => { setFollow(true); setPlaying(true); }}>Live</button>
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "420px 1fr", gap: 22, alignItems: "start" }}>
        <section className="kitchen" aria-live="polite"><Own a="guard" dark />
          <div style={{ color: "var(--onGreen)", fontSize: 15 }}>{date ? fmtMonthDay(date) : ""}</div>
          <div className="num" style={{ fontSize: 44, fontWeight: 700, lineHeight: 1.1 }}>{tick ? clock(tick.t) : clock(fromMin(span[0]))}</div>
          <div style={{ color: "var(--onGreen)", fontSize: 15, marginTop: 22 }}>Chashu left</div>
          <div style={{ fontSize: tick || par !== null ? 104 : 56, fontWeight: 700, lineHeight: tick || par !== null ? 1 : 1.86, color: tick && tick.believed_left < 40 ? "var(--cream)" : "#fff" }}>
            {tick ? <Tween value={tick.believed_left} ms={180} /> : par ?? "Ready"}
          </div>
          <div style={{ marginTop: 22, display: "flex", flexDirection: "column", gap: 10 }}>
            {CHANNELS.map((c) => {
              const v = tick?.sold[c] || 0;
              return (
                <div key={c} style={{ display: "grid", gridTemplateColumns: "92px 1fr 54px", gap: 10, alignItems: "center", fontSize: 14.5 }}>
                  <span style={{ color: "var(--onGreen2)" }}>{appName[c]}</span>
                  <HBar value={v} max={maxSold} color={tick && !tick.available[c] ? "#8b938e" : "#b8e986"} track="#2b6b5c" />
                  <b className="num" style={{ textAlign: "right", color: "var(--mint)" }}>{Math.round(v)}</b>
                </div>
              );
            })}
          </div>
          <div className="klog">
            {[...seen].reverse().slice(0, 6).map((e, i) => (
              <div key={`${e.t}${e.text}`} className={i === 0 ? "enter" : ""}>
                <span className="num">{e.t ? clock(e.t) : ""}</span>
                <span style={{ color: e.kind === "pause" ? "var(--mint)" : e.kind === "sold" ? "#f2a29d" : undefined }}>{e.text}</span>
              </div>
            ))}
          </div>
          {prompt && live && (
            <div role="dialog" aria-labelledby="rc-title" className="recount">
              <div id="rc-title" style={{ fontWeight: 700, fontSize: 17 }}>Quick count</div>
              <div style={{ fontSize: 14.5, color: "var(--ink2)", margin: "2px 0 12px" }}>About {prompt.believed_left} left by Gondola's count</div>
              <div style={{ display: "flex", gap: 10 }}>
                <span onKeyDown={(e) => e.key === "Enter" && answer()} style={{ flex: 1 }}>
                  <NumberField label="Portions counted" value={count} onChange={setCount} style={{ background: "#fff" }} />
                </span>
                <button className="btn" onClick={answer}>Send</button>
              </div>
            </div>
          )}
        </section>

        <div style={{ display: "flex", flexDirection: "column", gap: 22 }}>
          <div className="grid2" style={{ gap: 18 }}>
            {CHANNELS.map((c) => {
              const on = tick ? tick.available[c] : true;
              return (
                <div key={c} className={`card menu${on ? "" : " off"}`}>
                  <div style={{ display: "flex", justifyContent: "space-between", alignItems: "baseline" }}>
                    <h3><i className="sw" style={{ background: CH_COLOR[c] }} />{appName[c]}</h3>
                    <span style={{ fontSize: 14, fontWeight: 600, color: on ? "var(--good)" : "var(--crit)" }}>{on ? "Chashu on" : c === "in_store" ? "Sold out" : "Chashu paused"}</span>
                  </div>
                  <div style={{ marginTop: 8 }}>
                    {MENU.map(([name, price]) => {
                      const hasChashu = /Chashu|Tonkotsu|Shoyu|Miso/.test(name);
                      const off = !on && hasChashu;
                      return (
                        <div key={name} className="menurow" style={{ color: off ? "var(--muted)" : undefined }}>
                          <FoodIcon kind={name.includes("Don") || name.includes("Bao") ? "chashu" : "bowl"} size={26} />
                          <span style={{ fontSize: 15 }}>{name}</span>
                          <span className="num" style={{ fontSize: 14.5 }}>{off ? "Unavailable" : `$${c === "in_store" ? (Number(price) / 1.1).toFixed(2) : price}`}</span>
                        </div>
                      );
                    })}
                  </div>
                </div>
              );
            })}
          </div>
          <div className="grid2" style={{ gap: 18 }}>
            <div className="card" style={{ background: "var(--ink)", color: "#fff" }}>
              <div style={{ color: "#cfd6d2", fontSize: 14.5 }}>Without Gondola</div>
              <div className="num" style={{ fontSize: 56, fontWeight: 700, color: "#f2a29d" }}>{done?.status_quo_cancels ?? ov.data?.kpis?.avoidable_cancels ?? 0}</div>
              <div style={{ color: "#cfd6d2", fontSize: 14.5 }}>app cancels</div>
            </div>
            <div className="card" style={{ background: "var(--mint)" }}><Own a="guard" />
              <div style={{ fontSize: 14.5 }}>With Gondola</div>
              <div className="num" style={{ fontSize: 56, fontWeight: 700 }}>{done && follow ? done.cancels : tick ? <Tween value={tick.cancels} /> : "Ready"}</div>
              <div style={{ fontSize: 14.5 }}>app cancels{tick || done ? ` · ${Math.round(done && follow ? done.held_back : tick?.held_back ?? 0)} kept for dine-in` : ""}</div>
            </div>
          </div>
        </div>
      </div>
    </Page>
  );
}

function Scrubber({ span, buffered, at, events, onSeek }: { span: [number, number]; buffered: number; at: number; events: Ev[]; onSeek: (m: number) => void }) {
  const ref = useRef<HTMLDivElement>(null);
  const [drag, setDrag] = useState(false);
  const f = (m: number) => Math.max(0, Math.min(1, (m - span[0]) / (span[1] - span[0])));
  const seek = (clientX: number) => {
    const r = ref.current!.getBoundingClientRect();
    const m = span[0] + ((clientX - r.left) / r.width) * (span[1] - span[0]);
    onSeek(Math.min(buffered, Math.max(span[0], m)));
  };
  const hours = [];
  for (let h = Math.ceil(span[0] / 60); h * 60 <= span[1]; h++) hours.push(h * 60);
  return (
    <div className="scrubber" ref={ref} role="slider" tabIndex={0} aria-label="Replay time" data-keys data-testid="scrubber"
      aria-valuemin={span[0]} aria-valuemax={span[1]} aria-valuenow={Math.round(at)} aria-valuetext={clock(fromMin(at))}
      onPointerDown={(e) => { if (buffered <= span[0]) return; ref.current!.setPointerCapture(e.pointerId); setDrag(true); seek(e.clientX); }}
      onPointerMove={(e) => drag && seek(e.clientX)} onPointerUp={() => setDrag(false)}
      onKeyDown={(e) => { if (e.key === "ArrowLeft" || e.key === "ArrowRight") { e.preventDefault(); onSeek(Math.min(buffered, Math.max(span[0], at + (e.key === "ArrowRight" ? 5 : -5)))); } }}>
      <div className="scrub-track"><i className="buf" style={{ width: `${f(buffered) * 100}%` }} /><i className="played" style={{ width: `${f(at) * 100}%` }} /></div>
      {events.filter((e) => e.t).map((e) => <span key={e.t + e.text} className={`scrub-ev ${e.kind}`} style={{ left: `${f(toMin(e.t)) * 100}%` }} title={`${clock(e.t)} ${e.text}`} />)}
      <span className="scrub-knob" style={{ left: `${f(at) * 100}%` }} />
      {hours.map((m) => <span key={m} className="scrub-h" style={{ left: `${f(m) * 100}%` }}>{clock(fromMin(m)).replace(":00", "")}</span>)}
    </div>
  );
}
