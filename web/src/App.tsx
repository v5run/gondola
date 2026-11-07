import { NavLink, Navigate, Route, Routes, useLocation } from "react-router-dom";
import { AppProvider, LiveProvider, ToastProvider, useApp } from "./state";
import { PlaybackProvider } from "./playback";
import { WhyProvider } from "./why";
import { AgentProvider, AgentRail } from "./agents";
import { ExceptionsProvider, PresentProvider, useExceptions } from "./live";
import { Icon, Logo } from "./components/ui";
import { Page } from "./components/Page";
import { SECTIONS, sectionOf } from "./nav";
import Orders from "./screens/Orders";
import Insights from "./screens/Insights";
import CloseRun from "./screens/CloseRun";
import Service from "./screens/Service";
import Money from "./screens/Money";
import Reports from "./screens/Reports";
import Ask from "./screens/Ask";
import Alerts from "./screens/Alerts";
import Rush from "./screens/Rush";
import Flex from "./screens/Flex";
import OrderManager from "./screens/OrderManager";
import Queue from "./screens/Queue";
import RestOfToday from "./screens/RestOfToday";
import Tomorrow from "./screens/Tomorrow";
import Exceptions from "./screens/Exceptions";
import DayReview from "./screens/DayReview";
import ActionItems from "./screens/ActionItems";
import Knowledge from "./screens/Knowledge";
import Memory from "./screens/Memory";

export { useApp } from "./state";

const SHOW_ALERTS_TAB = false;

export default function App() {
  return (
    <AppProvider>
      <ToastProvider>
        <AgentProvider>
          <LiveProvider>
            <PresentProvider>
              <ExceptionsProvider>
                <WhyProvider>
                  <PlaybackProvider><Shell /></PlaybackProvider>
                </WhyProvider>
              </ExceptionsProvider>
            </PresentProvider>
          </LiveProvider>
        </AgentProvider>
      </ToastProvider>
    </AppProvider>
  );
}

function Shell() {
  const { mode } = useApp();
  const loc = useLocation();
  const cur = sectionOf(loc.pathname);
  const ex = useExceptions();
  return (
    <div className="shell">
      <nav className="side" aria-label="Main">
        <div className="logo"><Logo size={36} /></div>
        {SECTIONS.map((s) => (
          <NavLink key={s.key} to={s.base} className={`navlink${cur?.key === s.key ? " active" : ""}`} aria-label={s.name} aria-current={cur?.key === s.key ? "page" : undefined}>
            <Icon name={s.icon} />
            {s.key === "review" && ex.open > 0 && <i className="navdot" aria-label={`${ex.open} open exceptions`} />}
            <span className="tip">{s.name}</span>
          </NavLink>
        ))}
        <span className="navgap" />
        <NavLink to="/ask" className={({ isActive }) => `navlink${isActive ? " active" : ""}`} aria-label="Ask Gondola"><Icon name="ask" /><span className="tip">Ask Gondola</span></NavLink>
        {SHOW_ALERTS_TAB && <NavLink to="/alerts" className={({ isActive }) => `navlink${isActive ? " active" : ""}`} aria-label="Alerts"><Icon name="alerts" /><span className="tip">Alerts</span></NavLink>}
        <AgentRail />
        <div className="av" title="Maya, manager">MK</div>
      </nav>
      <main className="main">
        {mode === "mock" && <div className="offline" role="status"><i className="dot" />Backend offline Â· sample data</div>}
        <Routes>
          <Route path="/present/orders" element={<Page title="Present" live={false} date={false}><OrderManager /></Page>} />
          <Route path="/rush/orders" element={<Navigate to="/present/orders" replace />} />
          <Route path="/flex" element={<Page title="Present" live={false} date={false}><Flex /></Page>} />
          <Route path="/" element={<Navigate to="/present" replace />} />
          <Route path="/past" element={<Orders />} />
          <Route path="/past/money" element={<Money />} />
          <Route path="/past/reports" element={<Reports />} />
          <Route path="/past/insights" element={<Insights />} />
          <Route path="/present" element={<Queue />} />
          <Route path="/present/rush" element={<Page title="Present" live={false} date={false}><Rush /></Page>} />
          <Route path="/present/replay" element={<Service />} />
          <Route path="/future" element={<RestOfToday />} />
          <Route path="/future/tomorrow" element={<Tomorrow />} />
          <Route path="/future/days" element={<Navigate to="/future/tomorrow" replace />} />
          <Route path="/review" element={<Exceptions />} />
          <Route path="/review/close" element={<CloseRun />} />
          <Route path="/review/day" element={<DayReview />} />
          <Route path="/review/actions" element={<ActionItems />} />
          <Route path="/review/knowledge" element={<Knowledge />} />
          <Route path="/review/memory" element={<Memory />} />
          <Route path="/ask" element={<Ask />} />
          {SHOW_ALERTS_TAB && <Route path="/alerts" element={<Alerts />} />}
          {/* earlier addresses */}
          <Route path="/rush" element={<Navigate to="/present/rush" replace />} />
          <Route path="/tonight" element={<Navigate to="/past" replace />} />
          <Route path="/close" element={<Navigate to={`/review/close${loc.search}`} replace />} />
          <Route path="/tomorrow" element={<Navigate to="/future/tomorrow" replace />} />
          <Route path="/service" element={<Navigate to="/present/replay" replace />} />
          <Route path="/money" element={<Navigate to="/past/money" replace />} />
          <Route path="/reports" element={<Navigate to="/past/reports" replace />} />
          <Route path="/insights" element={<Navigate to="/past/insights" replace />} />
          <Route path="*" element={<Navigate to="/present" replace />} />
        </Routes>
      </main>
    </div>
  );
}
