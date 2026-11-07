/** Top-level workflows. Each has at most three plain-language tabs; everything else lives on its Details page
 *  (moved, never removed: every older screen keeps its route). */
export interface DetailLink { to: string; name: string; what: string }
export interface Section { key: string; name: string; icon: string; base: string; tabs: [string, string][]; details: DetailLink[] }
export const SECTIONS: Section[] = [
  { key: "present", name: "Present", icon: "present", base: "/present",
    tabs: [["/present", "Cook order"], ["/present/apps", "Apps"]],
    details: [
      { to: "/present/detail", name: "Full queue & kitchen", what: "Every factor per order, the response ladder, kitchen timeline, Gondola vs first-come, and the Rush agent log." },
      { to: "/present/orders", name: "Order manager", what: "Admit a burst of orders with four checked plans and saved receipts." },
      { to: "/present/rush", name: "Rush control", what: "Kitchen-aware promotions and the strategy lab." },
      { to: "/flex", name: "Flexible pickup", what: "Offer customers a discount for a later pickup time." },
      { to: "/present/replay", name: "Service replay", what: "Replay a night with the item safety net." },
    ] },
  { key: "future", name: "Future", icon: "future", base: "/future",
    tabs: [["/future", "Today"], ["/future/tomorrow", "Tomorrow"]],
    details: [
      { to: "/future/forecast", name: "Forecast charts", what: "Orders per 15 minutes by app, with ranges, and every driver behind the forecast." },
    ] },
  { key: "past", name: "Past", icon: "past", base: "/past",
    tabs: [["/past", "Summary"], ["/past/money", "Money"], ["/past/reports", "Reports"]],
    details: [
      { to: "/past/orders", name: "Orders & sales detail", what: "Charts, drill-downs and the full order log for any day." },
      { to: "/past/insights", name: "Insights", what: "Longer-term patterns across weeks and months." },
    ] },
  { key: "review", name: "Review", icon: "review", base: "/review",
    tabs: [["/review", "Needs attention"], ["/review/end-of-day", "End of day"], ["/review/actions", "To-do"]],
    details: [
      { to: "/review/close", name: "Close shift steps", what: "Run the nightly close and watch each agent step." },
      { to: "/review/exceptions", name: "All exceptions", what: "Every exception with evidence, including resolved ones." },
      { to: "/review/day", name: "Full day review", what: "Causes, evidence and knowledge changes from the review agent." },
      { to: "/review/knowledge", name: "Knowledge", what: "What Gondola has learned, with confidence." },
      { to: "/review/memory", name: "Memory", what: "Daily, weekly and monthly digests." },
    ] },
];
const owns = (s: Section, path: string) =>
  path === s.base || path.startsWith(`${s.base}/`) || s.details.some((d) => d.to === path);
export const sectionOf = (path: string) => SECTIONS.find((s) => owns(s, path)) || null;
