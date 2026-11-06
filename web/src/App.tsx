import { NavLink, Navigate, Route, Routes } from "react-router-dom";
import { AppProvider, LiveProvider, ToastProvider, useApp } from "./state";
import { WhyProvider } from "./why";
import { AgentProvider, AgentRail } from "./agents";
import { Icon, Logo } from "./components/ui";
import Tonight from "./screens/Tonight";
import Insights from "./screens/Insights";
import CloseRun from "./screens/CloseRun";
import Tomorrow from "./screens/Tomorrow";
import Service from "./screens/Service";
import Money from "./screens/Money";
import Reports from "./screens/Reports";
import Ask from "./screens/Ask";
import Alerts from "./screens/Alerts";
import Rush from "./screens/Rush";

export { useApp } from "./state";

const NAV = [
  ["/rush", "service", "Rush control"],
  ["/", "tonight", "Tonight"], ["/insights", "insights", "Insights"], ["/close", "close", "Close run"], ["/tomorrow", "tomorrow", "Tomorrow"],
  ["/service", "service", "Service"], ["/money", "money", "Money"], ["/reports", "reports", "Reports"],
  ["/ask", "ask", "Ask Gondola"], ["/alerts", "alerts", "Alerts"],
] as const;

export default function App() {
  return (
    <AppProvider>
      <ToastProvider>
        <AgentProvider>
        <LiveProvider>
          <WhyProvider>
            <Shell />
          </WhyProvider>
        </LiveProvider>
        </AgentProvider>
      </ToastProvider>
    </AppProvider>
  );
}

function Shell() {
  const { mode } = useApp();
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="logo"><Logo size={36} /></div>
        {NAV.map(([to, icon, label]) => (
          <NavLink key={to} to={to} end={to === "/"} className={({ isActive }) => `navlink${isActive ? " active" : ""}`} aria-label={label}>
            <Icon name={icon} />
            <span className="tip">{label}</span>
          </NavLink>
        ))}
        <AgentRail />
        <div className="av" title="Maya, manager">MK</div>
      </nav>
      <main className="main">
        {mode === "mock" && <div className="offline" role="status"><i className="dot" />Backend offline · sample data</div>}
        <Routes>
          <Route path="/rush" element={<Rush />} />
          <Route path="/" element={<Tonight />} />
          <Route path="/insights" element={<Insights />} />
          <Route path="/close" element={<CloseRun />} />
          <Route path="/tomorrow" element={<Tomorrow />} />
          <Route path="/service" element={<Service />} />
          <Route path="/money" element={<Money />} />
          <Route path="/reports" element={<Reports />} />
          <Route path="/ask" element={<Ask />} />
          <Route path="/alerts" element={<Alerts />} />
          <Route path="*" element={<Navigate to="/" />} />
        </Routes>
      </main>
    </div>
  );
}
