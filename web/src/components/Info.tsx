import { useEffect, useId, useLayoutEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { GLOSSARY } from "../lib/glossary";

/** A small "i" in the top-right of a metric or chart card. Hover, focus or click shows a short definition;
 *  Esc or a click outside closes it. Definitions live in lib/glossary.ts. */
export function Info({ k, text, dark, inline }: { k?: string; text?: string; dark?: boolean; inline?: boolean }) {
  const body = text ?? (k ? GLOSSARY[k] : "");
  const [open, setOpen] = useState<"hover" | "pin" | null>(null);
  const btn = useRef<HTMLButtonElement>(null);
  const pop = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ left: number; top: number }>({ left: -9999, top: 0 });
  const id = useId();
  const hide = useRef<ReturnType<typeof setTimeout>>();
  useLayoutEffect(() => {
    if (!open || !btn.current) return;
    const r = btn.current.getBoundingClientRect();
    const w = 280, h = pop.current?.offsetHeight || 80;
    const left = Math.max(10, Math.min(r.right - w, innerWidth - w - 10));
    const top = r.bottom + 8 + h > innerHeight - 10 ? Math.max(10, r.top - h - 8) : r.bottom + 8;
    setPos({ left, top });
  }, [open]);
  useEffect(() => {
    if (!open) return;
    const key = (e: KeyboardEvent) => { if (e.key === "Escape") { setOpen(null); btn.current?.focus(); } };
    const down = (e: MouseEvent) => { const t = e.target as Node; if (!btn.current?.contains(t) && !pop.current?.contains(t)) setOpen(null); };
    const scroll = () => setOpen(null);
    addEventListener("keydown", key); addEventListener("mousedown", down); addEventListener("scroll", scroll, true);
    return () => { removeEventListener("keydown", key); removeEventListener("mousedown", down); removeEventListener("scroll", scroll, true); };
  }, [open]);
  if (!body) return null;
  const enter = () => { clearTimeout(hide.current); setOpen((o) => o || "hover"); };
  const leave = () => { hide.current = setTimeout(() => setOpen((o) => (o === "hover" ? null : o)), 120); };
  return (
    <>
      <button ref={btn} type="button" className={`info${dark ? " dark" : ""}${inline ? " inline" : ""}`} aria-label="What is this?" aria-expanded={!!open}
        aria-describedby={open ? id : undefined} data-info={k}
        onClick={(e) => { e.stopPropagation(); e.preventDefault(); setOpen((o) => (o === "pin" ? null : "pin")); }}
        onMouseDown={(e) => e.stopPropagation()}
        onMouseEnter={enter} onMouseLeave={leave} onFocus={() => setOpen((o) => o || "hover")} onBlur={() => setOpen((o) => (o === "hover" ? null : o))}
        onKeyDown={(e) => e.stopPropagation()}>i</button>
      {open && createPortal(
        <div ref={pop} id={id} role="tooltip" className="infopop" style={{ left: pos.left, top: pos.top }} onMouseEnter={enter} onMouseLeave={leave}>{body}</div>,
        document.body)}
    </>
  );
}
