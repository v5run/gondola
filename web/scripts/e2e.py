"""End-to-end test of the Gondola web app (Past / Present / Future / Review) against the real API.

Usage (API running and web/dist built):
    GONDOLA_NOW=2026-11-05T19:30:00 python -m gondola.api      # mid-service on the demo night, real time from there
    python web/scripts/e2e.py [--base http://localhost:8000] [--chrome PATH] [--only present,review]

Blocks every request that is not to the app's own origin. Screenshots (1440x900) go to web/screenshots/tw-*.png.
Fails on console errors and on NaN/undefined text. Exits non-zero if any step fails.
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
BAD_TEXT = re.compile(r"\bNaN\b|undefined|Infinity|\[object Object\]")
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
                results.append((name, True, f"{note} ({time.time() - t0:.1f}s)"))
                print(f"PASS  {name}  {note}", flush=True)
            except Exception as e:  # noqa: BLE001
                results.append((name, False, str(e).splitlines()[0][:300]))
                print(f"FAIL  {name}  {e}", flush=True)
        run()
        return run
    return deco


def api(base: str, path: str, body: dict | None = None, method: str | None = None):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(f"{base}/api{path}", data=data, method=method or ("POST" if data else "GET"),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.loads(r.read())


def clean(page: Page, screen: str):
    text = page.locator("main").inner_text()
    m = BAD_TEXT.search(text)
    if m:
        raise AssertionError(f"{screen}: bad value {m.group(0)!r} near: {text[max(0, m.start() - 60): m.end() + 60]!r}")


def shot(page: Page, name: str):
    SHOTS.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SHOTS / f"tw-{name}.png"))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("GONDOLA_URL", "http://localhost:8000"))
    ap.add_argument("--chrome", default=os.environ.get("CHROME_PATH", "/usr/bin/google-chrome"))
    ap.add_argument("--only", default="")
    a = ap.parse_args()
    base = a.base.rstrip("/")
    ONLY.extend(x for x in a.only.split(",") if x)
    clk = api(base, "/now")
    today = clk["today"]
    errors: list[str] = []

    with sync_playwright() as p:
        kw = {"headless": True, "args": ["--no-sandbox"]}
        if a.chrome and Path(a.chrome).exists():
            kw["executable_path"] = a.chrome
        browser = p.chromium.launch(**kw)
        ctx = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=base)
        ctx.route("**/*", lambda r: r.continue_() if r.request.url.startswith(base) else r.abort())
        page = ctx.new_page()
        page.on("console", lambda m: m.type == "error" and errors.append(f"{page.url}: {m.text}"))
        page.on("pageerror", lambda e: errors.append(f"{page.url}: {e}"))
        page.set_default_timeout(60000)

        @step("Shell: workflows and Ask in the sidebar, Alerts hidden, grouped agent rail, real backend")
        def shell():
            page.goto("/")
            expect(page).to_have_url(re.compile(r"/present$"))
            nav = page.get_by_role("navigation", name="Main", exact=True)
            for name in ("Past", "Present", "Future", "Review", "Ask Gondola"):
                expect(nav.get_by_role("link", name=name, exact=True)).to_have_count(1)
            expect(nav.get_by_role("link", name="Alerts", exact=True)).to_have_count(0)
            assert page.locator(".offline").count() == 0, "offline banner against the real backend"
            groups = page.locator(".rail .railg").evaluate_all("els => els.map(e => e.getAttribute('aria-label'))")
            assert groups == ["Ledger", "Present", "Future", "Review"], groups
            page.goto("/alerts")
            expect(page).to_have_url(re.compile(r"/present$"))
            return f"clock {clk['now']} phase {clk['phase']}"

        @step("Present: queue board renders and updates live on the real clock")
        def present_live():
            page.goto("/present")
            rows = page.get_by_test_id("qrow")
            expect(rows.first).to_be_visible(timeout=90000)
            expect(page.get_by_test_id("headroom")).to_be_visible()
            page.wait_for_function("document.fonts.check('16px \"Inter Variable\"')")
            sig = lambda: page.get_by_test_id("queue").inner_text()  # noqa: E731
            s0, n0 = sig(), rows.count()
            clean(page, "Present")
            shot(page, "present")
            if clk["phase"] != "open":
                return f"{n0} rows (store closed: no live updates expected)"
            t0 = time.time()
            while time.time() - t0 < 100 and sig() == s0:
                page.wait_for_timeout(1000)
            assert sig() != s0, "queue did not change within 100 s"
            changed = time.time() - t0
            lit = page.locator(".rail .ag:not([data-n='0'])")
            while time.time() - t0 < 130 and lit.count() == 0:  # the next store minute brings orders: the rail lights
                page.wait_for_timeout(1000)
            assert lit.count() > 0, "no agent glyph lit by a live event"
            return f"{n0} -> {rows.count()} rows, changed after {changed:.0f}s; lit: {', '.join(lit.evaluate_all('els => els.map(e => e.dataset.agent)'))}"

        @step("Present: click a queue row shows its factors and reason")
        def present_factors():
            page.goto("/present")
            row = page.get_by_test_id("qrow").first
            expect(row).to_be_visible(timeout=90000)
            row.click()
            f = page.get_by_test_id("factors")
            expect(f).to_be_visible()
            n = f.locator(".frow").count()
            assert n == 7, f"{n} factor rows"
            reason = f.locator(".freason").inner_text()
            assert reason.strip(), "empty reason"
            page.wait_for_timeout(500)
            shot(page, "present-factors")
            page.keyboard.press("Enter")  # focused row toggles closed
            return f"reason: {reason[:60]}"

        @step("Present: ladder what-if and settings change")
        def present_ladder():
            page.goto("/present")
            expect(page.get_by_test_id("ladder")).to_be_visible(timeout=90000)
            page.locator(".gauge-zones button[data-level='busy']").click()
            pop = page.locator(".pop")
            expect(pop).to_contain_text("Headroom", timeout=90000)
            page.keyboard.press("Escape")
            before = api(base, "/present/settings")["ladder"]["hysteresis_min"]
            page.get_by_role("button", name="Ladder settings").click()
            expect(page.get_by_test_id("settings")).to_be_visible()
            field = page.locator("input[name='hysteresis_min']")
            field.fill(str(before + 1))
            shot(page, "present-settings")
            page.get_by_role("button", name="Save").click()
            expect(page.locator(".toast", has_text="Ladder settings saved")).to_be_visible()
            after = api(base, "/present/settings")["ladder"]["hysteresis_min"]
            assert after == before + 1, f"hysteresis {before} -> {after}"
            s = api(base, "/present/settings"); s["ladder"]["hysteresis_min"] = before
            api(base, "/present/settings", s, "PUT")
            return f"hysteresis {before} -> {after} (restored)"

        @step("Present: Rush agent run leaves a receipt")
        def present_agent():
            page.goto("/present")
            btn = page.get_by_test_id("run-agent")
            expect(btn).to_be_enabled(timeout=90000)
            btn.click()
            expect(page.get_by_test_id("agent-receipt")).to_be_visible(timeout=120000)
            return page.get_by_test_id("agent-receipt").inner_text().replace("\n", " ")[:80]

        @step("Present: Savvy's Rush Control still works")
        def rush():
            page.goto("/present/rush")
            expect(page.get_by_test_id("rush-workspace")).to_be_visible()
            expect(page.locator(".rush-replay")).to_be_visible(timeout=90000)
            expect(page.locator(".rush-stations .rush-station").first).to_be_visible()
            page.get_by_role("button", name="Strategy lab").click()
            expect(page.locator(".rush-lab")).to_be_visible()
            shot(page, "present-rush")
            return "service desk and strategy lab"

        @step("Past: orders processed, KPIs and the ledger feed")
        def past():
            page.goto("/past")
            expect(page.get_by_test_id("processed")).to_have_text(re.compile(r"\d"), timeout=60000)
            lines = page.get_by_test_id("ledger").locator(".lrow")
            expect(lines.first).to_be_visible()
            n = lines.count()
            page.get_by_role("radio", name="Decisions").click()
            expect(lines.first).to_be_visible()
            clean(page, "Past")
            page.get_by_role("radio", name="All").click()
            expect(page.get_by_test_id("ledger").locator(".lrow[data-type^='order']").first).to_be_visible()
            page.wait_for_timeout(600)
            shot(page, "past")
            return f"processed {page.get_by_test_id('processed').inner_text()}, {n} ledger lines"

        @step("Future: rest of today drivers, why on click, limited items")
        def future():
            page.goto("/future")
            d = page.get_by_test_id("drivers").locator(".olrow")
            expect(d.first).to_be_visible(timeout=60000)
            d.first.click()
            expect(page.get_by_test_id("driver-why")).to_be_visible()
            items = page.get_by_test_id("items").locator(".iclock")
            expect(items.first).to_be_visible()
            assert page.locator(".datec").count() == 0, "date control on Future"
            clean(page, "Future")
            shot(page, "future")
            return f"{d.count()} drivers, {items.count()} items"

        @step("Future: tomorrow only, forward, prep editable")
        def tomorrow():
            page.goto("/future/tomorrow")
            expect(page.get_by_test_id("day-p50")).to_be_visible(timeout=60000)
            assert page.locator(".datec, .daystrip").count() == 0, "past/day stepping on Tomorrow"
            expect(page.get_by_test_id("prep-handle")).to_be_visible(timeout=60000)
            label = page.locator(".hero .lab").first.inner_text()
            cards = page.get_by_test_id("prep-cards").locator(".prepc")
            expect(cards.first).to_be_visible()
            inp = cards.first.locator("input.num")
            if inp.is_enabled():
                v = int(re.sub(r"\D", "", inp.input_value()) or 0)
                inp.focus(); page.keyboard.press("ArrowUp")
                assert int(re.sub(r"\D", "", inp.input_value()) or 0) > v, "prep did not step"
            clean(page, "Tomorrow")
            shot(page, "future-tomorrow")
            return f"{label}; {cards.count()} prep cards"

        @step("Review: exceptions scan and resolve")
        def exceptions():
            page.goto("/review")
            page.get_by_test_id("scan").click()
            expect(page.locator(".toast").last).to_be_visible(timeout=120000)
            rows = page.get_by_test_id("exceptions").locator(".exrow")
            note = "none open"
            if rows.count():
                first = rows.first
                ident = first.get_attribute("data-id")
                first.get_by_test_id("resolve").click()
                expect(page.locator(".toast", has_text="Resolved")).to_be_visible()
                ex = api(base, f"/review/exceptions?date={today}")
                assert any(x["id"] == ident and x["resolved"] for x in ex), f"{ident} not resolved in the API"
                note = f"resolved {ident}"
            shot(page, "review-exceptions")
            return note

        @step("Review: knowledge base approve")
        def kb():
            page.goto("/review/knowledge")
            expect(page.get_by_test_id("kb")).to_be_attached(timeout=60000)
            btn = page.get_by_test_id("approve")
            if not btn.count():
                page.get_by_role("radio", name=re.compile("^All")).click()
                page.wait_for_timeout(800)
                shot(page, "review-knowledge")
                return "nothing waiting for approval"
            row = page.locator(".kbrow", has=btn.first)
            ident = row.first.get_attribute("data-id")
            page.wait_for_timeout(600)
            shot(page, "review-knowledge")
            btn.first.click()
            expect(page.locator(".toast", has_text="Approved")).to_be_visible()
            item = [x for x in api(base, "/review/kb") if x["id"] == ident][0]
            return f"{ident} -> {item['status']}"

        @step("Review: day review, action items, memory and context")
        def review_rest():
            for path, tid, name in (("/review/day", None, "review-day"), ("/review/actions", None, "review-actions"),
                                    ("/review/memory", "context-tokens", "review-memory"), ("/review/close", None, "review-close")):
                page.goto(path)
                if tid:
                    expect(page.get_by_test_id(tid)).to_be_visible(timeout=90000)
                page.wait_for_timeout(1500)
                clean(page, path)
                shot(page, name)
            return page.get_by_test_id("context-tokens").inner_text().replace("\n", " ") if page.get_by_test_id("context-tokens").count() else ""

        @step("Ask: chat answers and persists")
        def ask():
            page.goto("/ask")
            page.locator("#ask").fill("How many orders yesterday?")
            page.keyboard.press("Enter")
            answer = page.locator(".bub.bot:not(.typingb)").last
            expect(answer).to_be_visible(timeout=180000)
            page.reload()
            expect(page.locator(".bub.you").last).to_have_text("How many orders yesterday?")
            expect(answer).to_be_visible()
            shot(page, "ask")
            return answer.inner_text().replace("\n", " ")[:60]

        @step("No console errors")
        def console():
            bad = [e for e in errors if "favicon" not in e]
            assert not bad, "; ".join(bad[:5])

        browser.close()

    fails = [r for r in results if not r[1]]
    print(f"\n{len(results) - len(fails)}/{len(results)} passed")
    sys.exit(1 if fails else 0)


if __name__ == "__main__":
    main()
