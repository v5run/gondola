import { Link } from "react-router-dom";
import { Page } from "../components/Page";
import { SECTIONS } from "../nav";

/** A section's Details page: everything moved off the main tabs, one line each on what it is for. */
export default function Details({ section }: { section: string }) {
  const sec = SECTIONS.find((s) => s.key === section)!;
  return (
    <Page title={sec.name} date={false}>
      <div className="card dt">
        <h2>More in {sec.name}</h2>
        <p className="ink2">Detailed views for managers and the curious. The tabs above cover what you need during a shift.</p>
        <ul className="dt-list">
          {sec.details.map((d) => (
            <li key={d.to}><Link to={d.to}><b>{d.name}</b><span>{d.what}</span><i aria-hidden>→</i></Link></li>
          ))}
        </ul>
      </div>
    </Page>
  );
}
