import { useEffect, useRef, useState, type ReactNode } from "react";
import { NavLink, useLocation } from "react-router-dom";
import { useApp, useClock, useLive } from "../state";
import { PlaybackControls, usePlayback } from "../playback";
import { sectionOf } from "../nav";
import { D, iso } from "../lib/dates";
import { Icon, Segmented, clock } from "./ui";

/** Screen header: the workflow and its views (or a title), the global date control, screen actions, the live controls. */
export function Page({ title, actions, children, live = true, date = true }: { title: ReactNode; actions?: ReactNode; children: ReactNode; live?: boolean; date?: boolean }) {
  const loc = useLocation();
  const sec = sectionOf(loc.pathname);
  const { active } = usePlayback();
  return (
    <>
      <header className={`top${active ? " playback-top" : ""}`}>
        <div className="ttl">
          <h1>{sec ? sec.name : title}</h1>
          {sec && <nav className="tabs" aria-label={`${sec.name} views`}>
            {sec.tabs.map(([to, label]) => <NavLink key={to} to={to} end className={({ isActive }) => (isActive ? "on" : "")}>{label}</NavLink>)}
          </nav>}
        </div>
        {(date || active) && <DateControl />}
        <div className="right">
          {actions}
          {(live || active) && <LiveControl />}
        </div>
      </header>
      <PlaybackControls />
      {children}
    </>
  );
}

export function DateControl() {
  const { date, store, step, today, setDate } = useApp();
  const [open, setOpen] = useState(false);
  if (!date || !store) return <div className="datec"><span className="skeleton" style={{ width: 210, minHeight: 40 }} /></div>;
  const isToday = date === store.today;
  return (
    <div className="datec">
      <button className="iconbtn" onClick={() => step(-1)} disabled={date <= store.first_date} aria-label="Previous day" title="Previous day (←)"><Icon name="left" size={18} /></button>
      <button className="datec-label num" onClick={() => setOpen((o) => !o)} aria-haspopup="dialog" aria-expanded={open} aria-label="Pick a date" data-date={date}>
        {D(date).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric", year: date.slice(0, 4) !== store.today.slice(0, 4) ? "numeric" : undefined })}
      </button>
      <button className="iconbtn" onClick={() => step(1)} disabled={isToday} aria-label="Next day" title="Next day (→)"><Icon name="right" size={18} /></button>
      <button className="btn small light" onClick={today} disabled={isToday}>Today</button>
      {open && <MonthPicker value={date} min={store.first_date} max={store.today} onPick={(d) => { setDate(d); setOpen(false); }} onClose={() => setOpen(false)} />}
    </div>
  );
}

function MonthPicker({ value, min, max, onPick, onClose }: { value: string; min: string; max: string; onPick: (d: string) => void; onClose: () => void }) {
  const [ym, setYm] = useState(value.slice(0, 7));
  const ref = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const down = (e: MouseEvent) => { if (ref.current && !ref.current.parentElement!.contains(e.target as Node)) onClose(); };
    const key = (e: KeyboardEvent) => e.key === "Escape" && onClose();
    addEventListener("mousedown", down); addEventListener("keydown", key);
    return () => { removeEventListener("mousedown", down); removeEventListener("keydown", key); };
  }, [onClose]);
  const first = D(`${ym}-01`);
  const lead = first.getDay();
  const n = new Date(first.getFullYear(), first.getMonth() + 1, 0).getDate();
  const cells = [...Array(lead).fill(null), ...Array.from({ length: n }, (_, i) => `${ym}-${String(i + 1).padStart(2, "0")}`)];
  const shift = (k: number) => setYm(iso(new Date(first.getFullYear(), first.getMonth() + k, 1)).slice(0, 7));
  return (
    <div className="mpick" ref={ref} role="dialog" aria-label="Choose a date" data-keys>
      <div className="mpick-h">
        <button className="iconbtn" onClick={() => shift(-1)} disabled={`${ym}-01` <= min} aria-label="Previous month"><Icon name="left" size={16} /></button>
        <b>{first.toLocaleDateString("en-US", { month: "long", year: "numeric" })}</b>
        <button className="iconbtn" onClick={() => shift(1)} disabled={ym >= max.slice(0, 7)} aria-label="Next month"><Icon name="right" size={16} /></button>
      </div>
      <div className="mpick-g">
        {["S", "M", "T", "W", "T", "F", "S"].map((d, i) => <span key={i} className="muted">{d}</span>)}
        {cells.map((d, i) => d === null ? <span key={i} /> : (
          <button key={d} disabled={d < min || d > max} className={d === value ? "on" : d === max ? "now" : ""} onClick={() => onPick(d)}>{Number(d.slice(8))}</button>
        ))}
      </div>
    </div>
  );
}

/** A calm live dot and the real time while today is in service; "Closed" once the night is over. */
export function LiveControl() {
  const { view, setView, date, now, inService, today } = useApp();
  const t = useClock();
  const playback = usePlayback();
  const backToLive = () => { today(); setView("live"); };
  const live = useLive();
  const isToday = !!now && date === now.today;
  const on = view === "live" && isToday && inService && live.status !== "error";
  return (
    <div className={`livec${playback.active ? " playback-livec" : ""}`}>
      {view === "live" && isToday && <span className={`livedot${on ? " on" : ""}`} aria-hidden="true" />}
      {view === "live" && isToday && <span className="livec-clock num" aria-live="off" title={now ? `${now.tz.replace("_", " ")} time` : undefined}>
        {inService ? (t ? clock(t.slice(0, 5)) : "") : "Closed"}</span>}
      {playback.active && <span className="livec-clock num" data-testid="playback-clock">Playback · {playback.at} · {playback.speed} min/s</span>}
      <Segmented label="View" value={view} onChange={(next) => {
        if (next === "live") backToLive(); else setView(next);
      }} options={[["live", "Live"], ["playback", "Playback"]]} />
      {playback.active && <button className="btn small light" onClick={backToLive}>Back to live</button>}
    </div>
  );
}
