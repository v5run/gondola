/** Date helpers. All dates are ISO "YYYY-MM-DD" in store-local time; parse at noon to dodge DST edges. */
export const D = (iso: string) => new Date(`${iso}T12:00:00`);
export const iso = (d: Date) =>
  `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}`;
export const addDays = (s: string, n: number) => { const d = D(s); d.setDate(d.getDate() + n); return iso(d); };
export const daysBetween = (a: string, b: string) => Math.round((D(b).getTime() - D(a).getTime()) / 86400000);
export const clampDate = (s: string, lo?: string, hi?: string) => (lo && s < lo ? lo : hi && s > hi ? hi : s);
export const dowName = (s: string) => D(s).toLocaleDateString("en-US", { weekday: "long" });
export const fmtDay = (s: string) => D(s).toLocaleDateString("en-US", { weekday: "short", month: "short", day: "numeric" });
export const fmtMonthDay = (s: string) => D(s).toLocaleDateString("en-US", { month: "short", day: "numeric" });
export const fmtMonth = (ym: string) => D(`${ym.slice(0, 7)}-15`).toLocaleDateString("en-US", { month: "long", year: "numeric" });
export const fmtRange = (a: string, b: string) => (a === b ? fmtMonthDay(a) : `${fmtMonthDay(a)} – ${fmtMonthDay(b)}`);

/** "HH:MM" or "HH:MM:SS" -> minutes after midnight */
export const toMin = (t: string) => { const [h, m, s] = t.split(":").map(Number); return h * 60 + (m || 0) + (s || 0) / 60; };
export const fromMin = (m: number) => `${String(Math.floor(m / 60)).padStart(2, "0")}:${String(Math.floor(m % 60)).padStart(2, "0")}`;
