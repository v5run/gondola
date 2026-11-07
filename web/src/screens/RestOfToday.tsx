import { useEffect, useState } from "react";
import { tri, type FutureToday, type LimitedItem } from "../api/tri";
import { Page } from "../components/Page";
import { Info } from "../components/Info";
import { DriverList, ItemClock, NowcastChart } from "../components/future";
import { CH_COLOR, ErrorBox, Skeleton, Tween, appName, pct, shortDate } from "../components/ui";
import { toMin } from "../lib/dates";
import { useApp, useClock } from "../state";
import { Own } from "../agents";


/** Future › Rest of today. Always today (the store's business day); earlier days are in Past. */
export default function RestOfToday() {
  const { now, inService } = useApp();
  const clockNow = useClock();
  const today = now?.today || "";
  const [t, setT] = useState<FutureToday | null>(null);
  const [items, setItems] = useState<LimitedItem[] | null>(null);
  const [err, setErr] = useState<string | null>(null);
  const [itemsErr, setItemsErr] = useState<string | null>(null);
  const [ch, setCh] = useState("all");
  const [n, setN] = useState(0);
  useEffect(() => {
    if (!today) return;
    let dead = false;
    const pull = () => {
      tri.future.today(today).then((x) => { if (!dead) { setT(x); setErr(null); } }).catch((e) => !dead && setErr(String(e.message)));
      tri.future.items(today).then((x) => { if (!dead) { setItems(x.items); setItemsErr(null); } }).catch((e) => !dead && setItemsErr(String(e.message)));
    };
    pull();
    const id = inService ? setInterval(pull, 60000) : undefined;
    return () => { dead = true; if (id) clearInterval(id); };
  }, [today, inService, n]);
  const nowMin = inService && clockNow ? toMin(clockNow) : t?.now ? toMin(t.now) : null;
  const sf = t?.so_far;
  return (
    <Page title="Future" date={false}>
      {err && <ErrorBox error={err} retry={() => setN((x) => x + 1)} />}
      {!t && !err && <Skeleton h={330} />}
      {t && <section className="hero tonight-hero nowcast" aria-label="Rest of today"><Own a="forecaster" dark /><Info k="nowcast" dark />
        <div>
          <div className="lab">{shortDate(t.date)} · expected orders<Info k="expected_tonight" dark inline /></div>
          <div className="big"><Tween value={t.expected.p50} /><span className="num rng">{Math.round(t.expected.p10)}–{Math.round(t.expected.p90)}</span></div>
          <div className="drv">
            {sf && <div><span>So far</span><b className="num" data-testid="so-far">{sf.orders}{sf.vs_expected_pct !== null ? ` · ${pct(sf.vs_expected_pct, 0)} vs ${Math.round(sf.expected_by_now)}` : ""}</b></div>}
            <div><span>Still to come<Info k="rest_of_day" dark inline /></span><b className="num">{Math.round(t.rest.p50)} <span style={{ fontWeight: 500, color: "var(--onGreen)" }}>({Math.round(t.rest.p10)}–{Math.round(t.rest.p90)})</span></b></div>
          </div>
        </div>
        <div>
          <div className="nc-legend" role="radiogroup" aria-label="Channel">
            {["all", ...Array.from(new Set(t.bins.map((b) => b.channel)))].map((c) => <button key={c} role="radio" aria-checked={ch === c} className={ch === c ? "on" : ""} onClick={() => setCh(c)}>
              {c !== "all" && <i className="sw" style={{ background: CH_COLOR[c] }} />}{c === "all" ? "All channels" : appName[c]}</button>)}
          </div>
          <NowcastChart bins={t.bins} channel={ch} nowMin={nowMin} drivers={t.drivers} />
        </div>
      </section>}

      <div className="future-grid">
        <div className="card"><Own a="forecaster" /><Info k="drivers" />
          <div className="cardhead"><h3>Expected tonight</h3></div>
          {!t ? <Skeleton h={200} /> : <DriverList drivers={t.drivers} />}
        </div>
        <div className="card cream"><Own a="forecaster" /><Info k="runout" />
          <div className="cardhead"><h3>Limited items</h3></div>
          {itemsErr && <ErrorBox error={itemsErr} />}
          {!items && !itemsErr && <Skeleton h={220} />}
          {items && <div className="iclocks" data-testid="items">{items.map((it) => <ItemClock key={it.key} it={it} nowMin={nowMin} />)}</div>}
        </div>
      </div>
    </Page>
  );
}
