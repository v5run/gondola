/** Top-level workflows and their views. The sidebar shows the workflows; the page header shows the views. */
export interface Section { key: string; name: string; icon: string; base: string; tabs: [string, string][] }
export const SECTIONS: Section[] = [
  { key: "past", name: "Past", icon: "past", base: "/past", tabs: [["/past", "Orders"], ["/past/money", "Money"], ["/past/reports", "Reports"], ["/past/insights", "Insights"]] },
  { key: "present", name: "Present", icon: "present", base: "/present", tabs: [["/present", "Queue"], ["/present/rush", "Rush control"], ["/present/replay", "Service replay"]] },
  { key: "future", name: "Future", icon: "future", base: "/future", tabs: [["/future", "Rest of today"], ["/future/tomorrow", "Tomorrow"]] },
  { key: "review", name: "Review", icon: "review", base: "/review", tabs: [["/review", "Exceptions"], ["/review/close", "Close run"], ["/review/day", "Day review"], ["/review/actions", "Action items"], ["/review/knowledge", "Knowledge"], ["/review/memory", "Memory"]] },
];
export const sectionOf = (path: string) => SECTIONS.find((s) => path === s.base || path.startsWith(`${s.base}/`)) || null;
