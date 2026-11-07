/** Client copy of gondola/tools/plan.py:pause_times, so the Tomorrow card can move pause times while you drag. */
import type { Point } from "../api/types";
import { fromMin, toMin } from "./dates";

export const PAUSE_DELAY: Record<"doordash" | "ubereats" | "grubhub", number> = { doordash: 2, ubereats: 2, grubhub: 10 };
export const BUFFER_PORTIONS = 8;
export const APP_SHARE = 0.66;
/** Used only if neither the card nor the close carries portions_per_order (demo night value). */
export const FALLBACK_PPO = 1.082;

export function pauseTimes(curve: Point[], have: number, ppo: number, buffer = BUFFER_PORTIONS, appShare = APP_SHARE) {
  const out: Record<string, string | null> = {};
  for (const [app, delay] of Object.entries(PAUSE_DELAY)) {
    let cum = 0, t: string | null = null;
    for (const c of curve) {
      const rate = (c.orders * ppo) / 15;
      const need = buffer + rate * appShare * delay;
      cum += c.orders * ppo;
      if (have - cum <= need) { t = c.time; break; }
    }
    out[app] = t;
  }
  return out as Record<keyof typeof PAUSE_DELAY, string | null>;
}

/** Cumulative portions used by the end of each 15-minute slot. */
export function cumulative(curve: Point[], ppo: number) {
  let c = 0;
  return curve.map((p) => { c += p.orders * ppo; return { start: toMin(p.time), end: toMin(p.time) + 15, cum: c, slot: p.orders * ppo }; });
}

/** Minute of the day the portions run out (linear inside a slot), or null if they last. */
export function runOutMin(curve: Point[], have: number, ppo: number): number | null {
  let prev = 0;
  for (const s of cumulative(curve, ppo)) {
    if (s.cum >= have) return s.start + 15 * ((have - prev) / Math.max(1e-9, s.cum - prev));
    prev = s.cum;
  }
  return null;
}

/** Portions needed to last until minute `m`. */
export function portionsUntil(curve: Point[], m: number, ppo: number) {
  let prev = 0;
  for (const s of cumulative(curve, ppo)) {
    if (m <= s.end) return prev + s.slot * Math.max(0, (m - s.start) / 15);
    prev = s.cum;
  }
  return prev;
}

export const minLabel = (m: number) => fromMin(Math.round(m));
