const APP: Record<string, string> = { doordash: "DoorDash", ubereats: "Uber Eats", grubhub: "Grubhub", in_store: "Dine-in" };
/** "Gondola paused Chashu on DoorDash with 8 portions left…" -> "Chashu paused on DoorDash" */
export function shortEvent(e: { kind: string; text: string; app?: string }) {
  if (e.kind === "pause" && e.app) return `Chashu paused on ${APP[e.app] || e.app}`;
  if (e.kind === "sold_out") return "Chashu sold out";
  if (e.kind === "rush_start") return "Dinner rush";
  if (e.kind === "rush_end") return "Rush over";
  return e.text;
}
/** "8:39 PM" or "20:39" -> minutes after midnight */
export function minOf(t: string): number | null {
  const m = t.trim().match(/^(\d{1,2}):(\d{2})(?::\d{2})?\s*([ap]m)?$/i);
  if (!m) return null;
  let h = Number(m[1]);
  if (m[3]) { const pm = /p/i.test(m[3]); if (h === 12) h = pm ? 12 : 0; else if (pm) h += 12; }
  return h * 60 + Number(m[2]);
}
