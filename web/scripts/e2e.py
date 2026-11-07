"""End-to-end interaction test for the Gondola web app against the real API.

Usage (API must be running and web/dist built):
    python web/scripts/e2e.py [--base http://localhost:8000] [--chrome PATH]

Uses CHROME_PATH (or --chrome) if set, otherwise Playwright's bundled Chromium.
Blocks every request that is not to the app's own origin, so it also proves the app works offline.
Screenshots go to web/screenshots/ (v3-*.png). Exits non-zero if any step fails.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import Page, expect, sync_playwright

HERE = Path(__file__).resolve().parent
SHOTS = HERE.parent / "screenshots"
BAD_TEXT = re.compile(r"NaN|undefined|Infinity|\[object Object\]", re.M)

results: list[tuple[str, bool, str]] = []


ONLY: list[str] = []


def step(name: str):
    def deco(fn):
        def run(*a, **k):
            if ONLY and not any(o.lower() in name.lower() for o in ONLY):
                return
            t0 = time.time()
            try:
                note = fn(*a, **k) or ""
                results.append((name, True, f"{note} ({time.time() - t0:.1f}s)".strip()))
                print(f"PASS  {name}  {note}", flush=True)
            except Exception as e:  # noqa: BLE001
                results.append((name, False, str(e).splitlines()[0][:300]))
                print(f"FAIL  {name}  {e}", flush=True)
        return run
    return deco


def check_numbers(page: Page, screen: str):
    text = page.locator("main").inner_text()
    m = BAD_TEXT.search(text)
    if m:
        ctx = text[max(0, m.start() - 60): m.end() + 60].replace("\n", " | ")
        raise AssertionError(f"{screen}: bad value {m.group(0)!r} near: {ctx}")


def shot(page: Page, name: str, full: bool = False):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"v3-{name}.png"), full_page=full)


def api(base: str, path: str):
    with urllib.request.urlopen(f"{base}/api{path}", timeout=30) as r:
        return json.loads(r.read())


def num(s: str) -> float:
    s = s.replace("−", "-").replace("$", "").replace(",", "").strip()
    return float(re.findall(r"-?\d+(?:\.\d+)?", s)[0])


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("GONDOLA_URL", "http://localhost:8000"))
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH", ""))
    ap.add_argument("--headed", action="store_true")
    ap.add_argument("--only", default="", help="run only steps whose name contains this text (plus setup)")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    ONLY.extend([x for x in a.only.split(",") if x])
    console_errors: list[str] = []
    blocked: list[str] = []
    today = api(base, "/store")["today"]

    with sync_playwright() as p:
        kw = {"headless": not a.headed, "args": ["--no-sandbox"]}
        if a.chrome and Path(a.chrome).exists():
            kw["executable_path"] = a.chrome
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=base)
        ctx.grant_permissions(["clipboard-read", "clipboard-write"], origin=base)

        def gate(route):
            if route.request.url.startswith(base):
                route.continue_()
            else:
                blocked.append(route.request.url)
                route.abort()
        ctx.route("**/*", gate)
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and console_errors.append(m.text))
        page.on("pageerror", lambda e: console_errors.append(str(e)))
        page.set_default_timeout(20000)
        date_label = page.locator(".datec-label")
        if ONLY:
            page.goto("/")
            expect(date_label).to_be_visible()
        why_title = page.get_by_test_id("why-title")

        @step("Tonight: live stream ticks, KPIs count up, feed fills, no offline banner")
        def tonight_live():
            page.goto("/")
            expect(page.get_by_role("button", name="Close shift")).to_be_enabled()
            assert page.locator(".offline").count() == 0, "offline banner shown against the real backend"
            kpi = page.locator(".kpi", has_text="Orders").locator(".v")
            feed = page.get_by_test_id("feed").locator("> div")
            expect(feed.first).to_be_visible(timeout=20000)
            page.wait_for_timeout(600)
            o1, c1 = num(kpi.inner_text()), page.locator(".livec-clock").inner_text()
            page.wait_for_timeout(2200)
            o2, c2 = num(kpi.inner_text()), page.locator(".livec-clock").inner_text()
            assert o2 > o1, f"orders did not count up ({o1} -> {o2})"
            assert c1 != c2, f"live clock stuck at {c1}"
            loaded = page.evaluate("document.fonts.check('16px \"Inter Variable\"')")
            assert loaded, "Inter not loaded"
            check_numbers(page, "Tonight")
            shot(page, "tonight-live")
            return f"orders {o1:.0f} -> {o2:.0f}, clock {c1} -> {c2}, {feed.count()} feed rows"
        tonight_live()

        @step("Tonight: hover tooltip, click a 15-min point opens its breakdown")
        def tonight_why():
            page.get_by_role("radio", name="Day").click()
            svg = page.locator(".hero svg").first
            expect(svg).to_be_visible()
            bb = svg.bounding_box()
            x, y = bb["x"] + bb["width"] * 0.66, bb["y"] + bb["height"] * 0.5
            page.mouse.move(x, y)
            tip = page.locator(".hero .ctip")
            expect(tip).to_be_visible()
            tip_text = tip.inner_text().replace("\n", " ")
            shot(page, "tonight-tooltip")
            page.mouse.click(x, y)
            expect(page.get_by_test_id("why-bin")).to_be_visible()
            expect(page.get_by_test_id("why-bin").locator(".drv-row").first).to_be_visible()
            t = why_title.inner_text()
            page.keyboard.press("Escape")
            expect(page.get_by_test_id("why-bin")).to_have_count(0)
            check_numbers(page, "Tonight day view")
            shot(page, "tonight-day", full=True)
            return f"tooltip '{tip_text[:40]}', breakdown '{t}', Esc closed it"
        tonight_why()

        @step("Keyboard ←/→ steps the global date; Today returns")
        def keys():
            page.locator("h1").click()
            d0 = date_label.get_attribute("data-date")
            page.keyboard.press("ArrowLeft")
            expect(date_label).not_to_have_attribute("data-date", d0)
            d1 = date_label.get_attribute("data-date")
            page.keyboard.press("ArrowLeft")
            d2 = date_label.get_attribute("data-date")
            assert d0 > d1 > d2, f"{d0} {d1} {d2}"
            # every screen re-queries: Tonight shows the earlier day's numbers
            expect(page.locator(".hero .lab").first).to_be_visible()
            page.keyboard.press("ArrowRight")
            expect(date_label).to_have_attribute("data-date", d1)
            page.get_by_role("button", name="Today").click()
            expect(date_label).to_have_attribute("data-date", today)
            return f"{d0} → {d1} → {d2} → {d1} → Today"
        keys()

        @step("Insights: brush a range, breakdown shows drivers, double-click resets")
        def brush():
            page.get_by_role("link", name="Insights").click()
            ov = page.get_by_test_id("year-overlay")
            expect(ov).to_be_visible()
            expect(page.get_by_test_id("why-range")).to_be_visible(timeout=20000)
            head0 = page.locator(".rangehead h3").inner_text()
            bb = ov.bounding_box()
            y = bb["y"] + bb["height"] * 0.6
            page.mouse.move(bb["x"] + bb["width"] * 0.55, y)
            page.mouse.down()
            page.mouse.move(bb["x"] + bb["width"] * 0.62, y, steps=6)
            page.mouse.move(bb["x"] + bb["width"] * 0.70, y, steps=6)
            shot(page, "insights-brushing")
            page.mouse.up()
            head1 = page.locator(".rangehead h3").inner_text()
            assert head1 != head0, "brush did not change the range"
            expect(why_title).to_have_text(head1, timeout=20000)
            rng = page.get_by_test_id("why-range")
            expect(rng.locator(".drv-row").first).to_be_visible(timeout=20000)
            drivers = rng.locator(".drv-row").count()
            page.wait_for_timeout(400)
            shot(page, "insights-brush", full=True)
            # resize by dragging the right handle
            bb = ov.bounding_box()
            hx = page.evaluate("() => [...document.querySelectorAll('.handle rect')].map(r => r.getBoundingClientRect().x + 3)")
            page.mouse.move(hx[1], y); page.mouse.down(); page.mouse.move(hx[1] + 60, y, steps=5); page.mouse.up()
            head2 = page.locator(".rangehead h3").inner_text()
            assert head2 != head1, "handle drag did not resize"
            ov.dblclick(position={"x": bb["width"] * 0.3, "y": bb["height"] * 0.5})
            expect(page.locator(".rangehead h3")).to_have_text(head0)
            check_numbers(page, "Insights")
            return f"{head0} → {head1} ({drivers} driver rows) → {head2} → reset"
        brush()

        @step("Insights: click a day → breakdown, Open pops it out, pinned window swaps on next click")
        def drill():
            ov = page.get_by_test_id("year-overlay")
            bb = ov.bounding_box()
            y = bb["y"] + bb["height"] * 0.75
            page.mouse.click(bb["x"] + bb["width"] * 0.80, y)
            dayb = page.get_by_test_id("why-day")
            expect(dayb).to_be_visible()
            expect(dayb.locator(".drv-row").first).to_be_visible()
            t1 = why_title.inner_text()
            n_drv = dayb.locator(".drv-row").count()
            shot(page, "insights-day", full=True)
            page.get_by_role("button", name="Open", exact=True).click()
            win = page.get_by_test_id("why-window")
            expect(win).to_be_visible()
            win.get_by_role("button", name="Pin").click()
            page.wait_for_timeout(300)
            bb = ov.bounding_box()
            page.mouse.click(bb["x"] + bb["width"] * 0.40, bb["y"] + bb["height"] * 0.75)
            expect(win.get_by_test_id("why-title")).not_to_have_text(t1)
            t2 = win.get_by_test_id("why-title").inner_text()
            expect(win.get_by_test_id("why-day").locator(".drv-row").first).to_be_visible()
            shot(page, "why-window")
            win.get_by_role("button", name="Close breakdown").click()
            expect(win).to_have_count(0)
            return f"inline {t1} ({n_drv} driver rows) → window swapped to {t2}"
        drill()

        @step("Close shift: chashu left 0, run reaches done over SSE")
        def close():
            page.get_by_role("link", name="Tonight").click()
            page.get_by_role("button", name="Close shift").click()
            page.locator("#cnt-Chashu").fill("0")
            page.get_by_role("button", name="Start the close").click()
            page.wait_for_url(re.compile(r"/close\?run="))
            page.wait_for_timeout(150)
            shot(page, "close-running")
            expect(page.get_by_text(re.compile(r"Finished in [\d.]+s"))).to_be_visible(timeout=60000)
            expect(page.get_by_text("8 of 8 done")).to_be_visible()
            title = page.locator("h3", has_text=re.compile(r"^(Text|No text)")).inner_text()
            detail = api(base, f"/closes/{today}")
            urgent = [f for f in detail["findings"] if f.get("urgency") == "urgent"]
            if urgent:
                assert "nothing urgent" not in title, f"says {title!r} with {len(urgent)} urgent findings"
            first = page.locator(".card.cream .dot").first.get_attribute("style") or ""
            assert not urgent or "crit" in first, "Findings do not start with an urgent finding"
            check_numbers(page, "Close run")
            shot(page, "close")
            # the agent rail recorded each agent's last action from the SSE stream
            lit = page.evaluate("() => [...document.querySelectorAll('.rail [data-agent]')].filter(e => e.dataset.last).map(e => e.dataset.agent)")
            for a in ["coordinator", "books", "stock", "demand", "analyst", "plan"]:
                assert a in lit, f"rail has no action for {a}: {lit}"
            return f"text card: {title!r}; rail lit {len(lit)} agents"
        close()

        @step("Tomorrow: drag the run-out handle moves pause times, edit prep, approve")
        def tomorrow():
            page.get_by_role("link", name="Review tomorrow's card").click()
            page.wait_for_url(re.compile(r"/tomorrow"))
            inp = page.locator("#prep-0")
            expect(inp).to_be_visible()
            if inp.is_disabled():
                page.get_by_role("button", name="Edit plan").click()
                expect(inp).to_be_enabled()
            orig = int(inp.input_value())
            cells = page.locator("tr[data-app] td.pz")
            before = cells.all_inner_texts()
            handle = page.get_by_test_id("prep-handle")
            hb = page.locator("[data-testid=prep-handle] rect").nth(1).bounding_box()
            svg = page.locator(".hero svg").first.bounding_box()
            sx, sy = hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2
            tx = svg["x"] + svg["width"] * 0.72
            page.mouse.move(sx, sy); page.mouse.down()
            page.mouse.move((sx + tx) / 2, sy, steps=5)
            page.mouse.move(tx, sy, steps=5)
            shot(page, "tomorrow-drag")
            page.mouse.up()
            after = cells.all_inner_texts()
            dragged = int(inp.input_value())
            assert dragged < orig, f"prep did not drop ({orig} -> {dragged})"
            assert after != before, f"pause times did not move: {before} -> {after}"
            assert any(re.search(r"\d:\d\d [ap]m", t) for t in after), f"no pause time after drag: {after}"
            label = handle.get_attribute("aria-valuetext")
            # keyboard on the number field
            inp.focus(); page.keyboard.press("ArrowUp")
            assert int(inp.input_value()) == dragged + 10, "arrow key did not step prep"
            new = orig - 10
            inp.fill(str(new))
            page.get_by_role("button", name=re.compile(r"^Approve")).click()
            expect(page.get_by_role("button", name=re.compile(r"^Approv"))).to_be_disabled()
            expect(page.get_by_role("button", name="Approved")).to_be_visible()
            card = api(base, f"/closes/{today}")
            assert card["approved"], "API does not show approved"
            assert int(card["card"][0]["prep"]) == new, f"API prep {card['card'][0]['prep']} != edited {new}"
            check_numbers(page, "Tomorrow")
            shot(page, "tomorrow")
            card["card"][0]["prep"] = orig
            req = urllib.request.Request(f"{base}/api/closes/{card['date']}/approve", method="POST",
                                         data=json.dumps({"card": card["card"]}).encode(), headers={"Content-Type": "application/json"})
            urllib.request.urlopen(req, timeout=30).read()
            return f"drag {orig}→{dragged} ({label}); pause {before} → {after}; approved {new}"
        tomorrow()

        @step("Service replay at max speed, recount answered, apps paused, scrub back in time")
        def service():
            page.get_by_role("link", name="Service").click()
            sel = page.locator("#speed")
            speeds = [int(v) for v in sel.locator("option").evaluate_all("o => o.map(x => x.value)")]
            sel.select_option(str(max(speeds)))
            page.get_by_role("button", name=re.compile(r"Start service|Replay again")).click()
            dlg = page.get_by_role("dialog", name="Quick count")
            dlg.wait_for(timeout=60000)
            believed = int(dlg.get_by_label("Portions counted").input_value() or 0)
            # the replay makes the kitchen 6% short of what Gondola believes; the line counts what is really there
            so = (api(base, f"/closes/{today}").get("sold_out") or {})
            par = float(so.get("prepped") or 479)
            counted = max(0, believed - round(par * 0.06))
            dlg.get_by_label("Portions counted").fill(str(counted))
            dlg.get_by_role("button", name="Send").click()
            expect(page.get_by_role("button", name="Replay again")).to_be_visible(timeout=120000)
            without = page.locator(".card", has_text="Without Gondola").locator(".num").first.inner_text()
            with_ = page.locator(".card", has_text="With Gondola").locator(".num").first.inner_text()
            assert without.strip().isdigit() and with_.strip().isdigit(), f"counts not numeric: {without!r} / {with_!r}"
            paused = page.locator(".menu", has_text="Chashu paused").count()
            assert paused == 3, f"{paused} apps paused"
            log = page.locator("section[aria-live]").inner_text()
            assert "Line counted" in log, "manager count not in log"
            assert "No reply" not in log, "manager answer was ignored by the backend"
            end_t = page.locator(".scrub-t").inner_text()
            sb = page.get_by_test_id("scrubber").bounding_box()
            page.mouse.move(sb["x"] + sb["width"] * 0.55, sb["y"] + 14); page.mouse.down()
            page.mouse.move(sb["x"] + sb["width"] * 0.3, sb["y"] + 14, steps=5); page.mouse.up()
            mid_t = page.locator(".scrub-t").inner_text()
            assert mid_t != end_t, "scrubber did not move the replay"
            paused_mid = page.locator(".menu", has_text="Chashu paused").count()
            shot(page, "service-scrub")
            page.get_by_role("button", name="Play", exact=True).click()
            page.wait_for_timeout(1200)
            played_t = page.locator(".scrub-t").inner_text()
            assert played_t != mid_t, "play did not advance from the scrubbed point"
            check_numbers(page, "Service")
            return f"counted {counted} (believed {believed}); without {without} vs with {with_}; scrubbed {end_t} → {mid_t} ({paused_mid} paused then) → play {played_t}"
        service()

        @step("Money: app payout rows, dispute drawer with evidence + copy")
        def money():
            page.get_by_role("link", name="Money").click()
            rows = page.locator(".card", has_text="Dispute checklist").locator("tbody tr")
            expect(rows.first).to_be_visible()
            n = rows.count()
            assert n <= 8, f"{n} dispute rows"
            days = rows.locator("td:nth-child(5)").all_inner_texts()
            vals = [0 if d == "Today" else int(d) for d in days]
            assert vals == sorted(vals), f"not sorted by days left: {vals}"
            pr = page.get_by_test_id("payout-rows")
            page.get_by_role("button", name=re.compile("Uber Eats")).first.click()
            expect(page.get_by_role("button", name=re.compile("Uber Eats")).first).to_have_attribute("aria-pressed", "true")
            ue = pr.inner_text()
            page.get_by_role("button", name=re.compile("DoorDash")).first.click()
            assert pr.inner_text() != ue or "Pending" in ue, "payout rows did not change per app"
            rows.first.locator("td").nth(2).click()
            ev = page.get_by_test_id("evidence")
            expect(ev).to_be_visible()
            page.get_by_role("button", name="Copy evidence", exact=True).click()
            clip = page.evaluate("navigator.clipboard.readText()")
            assert clip == ev.inner_text().strip(), "clipboard does not match evidence"
            shot(page, "money-dispute")
            page.keyboard.press("Escape")
            expect(page.get_by_test_id("evidence")).to_have_count(0)
            # hovering Books in the rail rings every number Books owns; hovering a number's mark lights Books in the rail
            page.locator(".rail [data-agent=books]").hover()
            page.wait_for_timeout(350)
            ring = page.evaluate("() => [...document.querySelectorAll('[data-owner=books]')].filter(e => getComputedStyle(e).boxShadow.includes('184, 233, 134')).length")
            other = page.evaluate("() => [...document.querySelectorAll('[data-owner]:not([data-owner=books])')].filter(e => getComputedStyle(e).boxShadow.includes('184, 233, 134')).length")
            assert ring >= 3 and other == 0, f"books ring on {ring}, others {other}"
            tip = page.locator(".rail [data-agent=books] .tip").inner_text()
            page.wait_for_timeout(250)
            shot(page, "agents")
            page.mouse.move(700, 880)
            page.locator("[data-owner=books] > .og").first.hover()
            page.wait_for_timeout(350)
            bg = page.evaluate("getComputedStyle(document.querySelector('.rail [data-agent=books]')).backgroundColor")
            assert bg == "rgb(184, 233, 134)", f"rail glyph not lit: {bg}"
            page.mouse.move(700, 880)
            check_numbers(page, "Money")
            return f"{n} disputes; evidence copied ({len(clip)} chars); Books rings {ring} numbers, tip '{tip}'"
        money()

        @step("Reports: heatmap + list, filter texted, search, open, rebuild an expired night")
        def reports():
            page.get_by_role("link", name="Reports").click()
            lst = page.get_by_test_id("report-list")
            expect(lst.locator(".rrow").first).to_be_visible()
            total = lst.locator(".rrow").count()
            cells = page.get_by_test_id("heatmap").locator("button:not([disabled])").count()
            assert total >= 30 and cells >= 30, f"only {total} rows / {cells} heat cells"
            frame = page.frame_locator(".viewer iframe")
            expect(frame.locator("body")).to_contain_text(re.compile(r"\S"), timeout=20000)
            page.get_by_role("radio", name="Texted").click()
            texted = lst.locator(".rrow")
            nt = texted.count()
            assert 0 < nt < total, f"texted filter shows {nt} of {total}"
            assert all("Texted" in t for t in texted.all_inner_texts()), "non-texted night in texted filter"
            page.get_by_role("radio", name="All").click()
            page.get_by_label("Search reports").fill("strong")
            ns = lst.locator(".rrow").count()
            assert 0 < ns < total, f"search shows {ns}"
            page.get_by_label("Search reports").fill("")
            # click a heatmap day → viewer + global date follow
            cell = page.get_by_test_id("heatmap").locator("button:not([disabled])").nth(3)
            d = cell.get_attribute("data-date")
            cell.click()
            expect(date_label).to_have_attribute("data-date", d)
            exp = lst.locator(".rrow", has=page.get_by_role("button", name="Rebuild"))
            note = "no expired nights"
            if exp.count():
                row = exp.last
                dd = row.get_attribute("data-date")
                row.get_by_role("button", name="Rebuild").click()
                expect(lst.locator(f".rrow[data-date='{dd}']")).to_contain_text("Rebuilt", timeout=60000)
                expect(page.frame_locator(".viewer iframe").locator("body")).to_contain_text(re.compile(r"\S"), timeout=30000)
                st = [r for r in api(base, "/reports") if r["date"] == dd and r["kind"] == "daily"][0]["status"]
                note = f"rebuilt {dd} (API status {st})"
            m = page.get_by_test_id("monthly").first
            if m.count():
                m.click()
                expect(page.frame_locator(".viewer iframe").locator("body")).to_contain_text(re.compile(r"\S"), timeout=30000)
            href = page.get_by_role("link", name="Open PDF").get_attribute("href")
            r = page.request.get(href)
            assert r.ok and r.headers.get("content-type", "").startswith("application/pdf"), f"{href}: {r.status}"
            check_numbers(page, "Reports")
            shot(page, "reports", full=True)
            return f"{total} nights, {nt} texted, {ns} match 'strong', {note}"
        reports()

        @step("Ask: 4 questions, clarify + chart render")
        def ask():
            page.get_by_role("link", name="Ask Gondola").click()
            qs = ["How did we do tonight vs a usual Thursday?", "how were sales", "DoorDash sales last week?", "uber vs doordash last month"]
            bubbles = page.locator("[aria-live=polite] > div[style*='flex-start']")
            for i, q in enumerate(qs, 1):
                page.locator("#ask").fill(q)
                page.get_by_role("button", name="Ask", exact=True).click()
                expect(bubbles).to_have_count(i, timeout=60000)
                txt = bubbles.nth(i - 1).inner_text()
                assert txt.strip() and "Something went wrong" not in txt, f"{q!r}: {txt[:120]}"
            assert "Asking what you mean" in bubbles.nth(1).inner_text(), "vague question did not clarify"
            assert bubbles.nth(2).locator("svg").count() == 1, "no chart for DoorDash last week"
            check_numbers(page, "Ask")
            shot(page, "ask")
            return "clarify + chart ok"
        ask()

        @step("Alerts: reply 1 and a question over SMS")
        def alerts():
            page.get_by_role("link", name="Alerts").click()
            page.get_by_role("button", name="Today").click() if page.get_by_role("button", name="Today").is_enabled() else None
            page.wait_for_load_state("networkidle")
            box = page.get_by_label("Reply")
            out = []
            for body in ["1", "why did we run out of chashu?"]:
                n_before = page.locator("[aria-live=polite] > div[style*='flex-start']").count()
                box.fill(body)
                page.get_by_role("button", name="Send").click()
                expect(page.locator("[aria-live=polite] > div[style*='flex-start']")).to_have_count(n_before + 1, timeout=60000)
                reply = page.locator("[aria-live=polite] > div[style*='flex-start']").last.inner_text()
                assert reply and "Couldn't reach" not in reply, reply
                out.append(reply[:60])
            assert "/home/" not in page.locator("main").inner_text(), "server path leaked"
            check_numbers(page, "Alerts")
            shot(page, "alerts")
            return " | ".join(out)
        alerts()

        @step("No console errors, no external requests")
        def hygiene():
            errs = [e for e in console_errors if "favicon" not in e]
            assert not errs, f"console errors: {errs[:3]}"
            assert not blocked, f"external requests: {blocked[:3]}"
            return "clean"
        hygiene()

        for path, name in ([] if ONLY else [("/insights", "insights"), ("/close", "close-static"), ("/service", "service"), ("/money", "money")]):
            page.goto(path)
            page.wait_for_load_state("networkidle")
            page.wait_for_timeout(800)
            shot(page, name, full=True)
        browser.close()

    print("\nSummary")
    for name, ok, note in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}  {note}")
    sys.exit(0 if all(ok for _, ok, _ in results) else 1)


if __name__ == "__main__":
    main()
