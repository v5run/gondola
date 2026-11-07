"""Real local UI checks and captioned recording. One actual Gemini job is intentional.

Only restaurant data, orders, payments and the explicitly injected error are
simulated. The browser uses the running FastAPI app and its shared SQLite ledger.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "demo"
BASE = "http://127.0.0.1:8000"


def run():
    checks, errors = [], []
    OUT.mkdir(parents=True, exist_ok=True)
    def passed(name):
        checks.append(name)
        print("PASS", name, flush=True)

    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1040})
        page = context.new_page()
        page.on("pageerror", lambda e: errors.append(str(e)))

        def episode(**settings):
            r = context.request.post(BASE + "/api/flex/sessions", data=settings)
            assert r.ok, r.text()
            return r.json()

        def open_session(s, page=page, merchant=False):
            page.goto(f"{BASE}/flex?s={s['id']}" + ("&view=merchant" if merchant else ""))
            expect(page.get_by_role("button", name="Find my pickup options", exact=True) if not merchant else page.get_by_role("heading", name="Make the flexibility real.")).to_be_visible()
            if not merchant: expect(page.get_by_role("button", name="Find my pickup options", exact=True)).to_be_enabled()

        def quote(page=page, agent=False):
            if agent:
                page.get_by_role("button", name="Let Gemini find options", exact=True).click()
                expect(page.locator(".flex-source")).to_have_text("Choices selected by real Gemini tools", timeout=120_000)
                expect(page.locator(".flex-agent-trace")).to_contain_text("Checked choices. Your decision.")
                return None
            with page.expect_response(lambda r: "/quotes" in r.url and r.request.method == "POST") as response:
                page.get_by_role("button", name="Find my pickup options", exact=True).click()
            assert response.value.ok, response.value.text()
            expect(page.get_by_role("button", name="Confirm this pickup", exact=True)).to_be_enabled()
            return response.value.json()

        def current(s): return context.request.get(BASE + f"/api/flex/sessions/{s['id']}").json()

        s = episode()
        open_session(s)
        q = quote()
        assert [(o["pickup_clock"], o["price_cents"]) for o in q["options"]] == [("17:53", 1540), ("18:15", 1340), ("18:20", 1240)]
        assert not current(s)["bookings"] and current(s)["spent_cents"] == 0
        page.screenshot(path=str(OUT / "flex-checkout.png"), full_page=True)
        page.get_by_role("button", name="Confirm this pickup", exact=True).click()
        expect(page.get_by_test_id("flex-receipt")).to_contain_text("Cooking 18:11–18:14")
        saved = current(s)
        assert len(saved["bookings"]) == 1 and saved["spent_cents"] == 200 and saved["menu"]["don"]["available"] == s["menu"]["don"]["available"] - 1
        assert saved["base_plan"] == s["base_plan"]
        page.reload()
        expect(page.get_by_test_id("flex-receipt")).to_be_visible()
        page.get_by_role("button", name="See what changed in the kitchen ↗").click()
        expect(page.get_by_test_id("flex-production-proof")).to_contain_text("3 near-term cook-minutes released")
        expect(page.get_by_test_id("flex-production-proof")).to_contain_text("Cooking 17:49–17:52")
        page.screenshot(path=str(OUT / "flex-kitchen.png"), full_page=True)
        passed("Choice reserves moved cook/pack slots, spends $2 once, decrements stock, preserves existing work and reloads receipt")

        owner_context = browser.new_context(viewport={"width": 1440, "height": 1040})
        owner = owner_context.new_page()
        owner.on("pageerror", lambda e: errors.append(str(e)))
        open_session(s, owner, merchant=True)
        expect(owner.get_by_test_id("flex-production-proof")).to_contain_text("CONFIRMED CHOICE")
        owner.get_by_role("button", name="Customer checkout", exact=True).click()
        expect(owner.get_by_test_id("flex-receipt")).to_have_count(0)
        passed("Independent merchant view reads shared evidence without adopting another customer's receipt")
        owner_context.close()

        s = episode(); open_session(s); quote()
        page.get_by_role("radio").first.click()
        page.get_by_role("button", name="Confirm this pickup", exact=True).click()
        expect(page.get_by_test_id("flex-receipt")).to_contain_text("Cooking 17:49–17:52")
        assert current(s)["spent_cents"] == 0
        passed("Customer can keep earliest regular-price pickup")

        s = episode(); open_session(s); quote()
        page.get_by_role("button", name="Not now — leave without ordering", exact=True).click()
        expect(page.get_by_role("heading", name="Dinner on your terms.")).to_be_visible()
        assert not current(s)["bookings"] and current(s)["spent_cents"] == 0
        passed("Declining makes no order and spends nothing")

        s = episode(quote_ttl_seconds=5); open_session(s); quote()
        expect(page.locator(".flex-expiry")).to_contain_text("quote expired", timeout=8000)
        expect(page.get_by_role("button", name="Confirm this pickup", exact=True)).to_be_disabled()
        assert not current(s)["bookings"]
        passed("Expired quote disables confirmation and reserves nothing")

        s = episode(); open_session(s); quote()
        page.get_by_role("button", name="Kitchen & evidence", exact=True).click()
        page.get_by_role("button", name="Book this slot for another customer", exact=True).click()
        expect(page.locator(".flex-owner-grid")).to_contain_text("OTHER-")
        page.get_by_role("button", name="Customer checkout", exact=True).click()
        page.get_by_role("button", name="Confirm this pickup", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("slot just filled")
        expect(page.get_by_role("button", name="Confirm this pickup", exact=True)).to_be_disabled()
        assert len(current(s)["bookings"]) == 1 and current(s)["spent_cents"] == 0
        page.screenshot(path=str(OUT / "flex-conflict.png"), full_page=True)
        page.get_by_role("button", name="Refresh pickup options", exact=True).click()
        expect(page.get_by_role("button", name="Confirm this pickup", exact=True)).to_be_enabled()
        passed("Competing reservation rejects stale confirmation with no extra booking or spend; refreshed options work")

        s = episode(); open_session(s); quote()
        second_context = browser.new_context(viewport={"width": 1200, "height": 1000})
        other = second_context.new_page(); other.on("pageerror", lambda e: errors.append(str(e)))
        open_session(s, other); quote(other)
        page.get_by_role("button", name="Confirm this pickup", exact=True).click()
        expect(page.get_by_test_id("flex-receipt")).to_be_visible()
        other.get_by_role("button", name="Confirm this pickup", exact=True).click()
        expect(other.get_by_role("alert")).to_contain_text("slot just filled")
        assert len(current(s)["bookings"]) == 1 and current(s)["spent_cents"] == 200
        second_context.close()
        passed("Two independent customer checkouts cannot confirm the same production slot")

        for settings, prefs in [({"scenario": "quiet"}, {}), ({"budget_cents": 0}, {}), ({}, {"Minimum saving": "400"}), ({}, {"Latest pickup": "25"})]:
            s = episode(**settings); open_session(s)
            for label, value in prefs.items(): page.get_by_label(label, exact=True).select_option(value)
            q = quote()
            assert len(q["options"]) == 1 and q["no_deal_reason"]
            expect(page.get_by_test_id("flex-no-deal")).to_be_visible()
        s = episode(scenario="overload", cooks=1); open_session(s)
        page.get_by_label("Latest pickup", exact=True).select_option("25")
        page.get_by_role("button", name="Find my pickup options", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("No pickup fits")
        expect(page.get_by_role("radio")).to_have_count(0)
        passed("Quiet/budget/preference/deadline and overload cases do not fabricate bargains or available slots")

        s = episode(); open_session(s)
        page.route("**/api/flex/sessions/*/agent", lambda route: route.fulfill(status=503, content_type="application/json", body=json.dumps({"detail": "Injected provider outage: no proposals were published"})))
        expect(page.get_by_role("button", name="Let Gemini find options", exact=True)).to_be_enabled()
        page.get_by_role("button", name="Let Gemini find options", exact=True).click()
        expect(page.get_by_role("alert")).to_contain_text("Injected provider outage")
        expect(page.get_by_role("radio")).to_have_count(0)
        assert not current(s)["quote_summaries"]
        page.unroute("**/api/flex/sessions/*/agent")
        passed("Injected provider failure remains an error, with no fake AI result or automatic planner fallback")

        # Caption overlay belongs only to this recording, not the product bundle.
        record = browser.new_context(viewport={"width": 1440, "height": 1040}, record_video_dir=str(ROOT / ".local" / "flex-video"), record_video_size={"width": 1440, "height": 1040})
        demo = record.new_page(); demo.on("pageerror", lambda e: errors.append(str(e)))
        def caption(text):
            demo.evaluate("""text => { let el=document.getElementById('demo-caption'); if(!el){el=document.createElement('div');el.id='demo-caption';el.style.cssText='position:fixed;bottom:18px;left:120px;right:36px;z-index:9999;background:#102e26ef;color:#fff;padding:18px 24px;border-radius:12px;font:17px Inter, sans-serif;box-shadow:0 8px 35px #0003;pointer-events:none';document.body.append(el)} el.textContent=text }""", text)
        s = episode(); open_session(s, demo)
        caption("Synthetic rush, real Gemini. The customer chooses a deadline and minimum worthwhile saving.")
        demo.wait_for_timeout(1800)
        quote(demo, agent=True)
        assert not current(s)["bookings"] and current(s)["spent_cents"] == 0
        expect(demo.locator(".rush-tool-log")).to_contain_text("Published checked choices")
        caption("Gemini used kitchen tools to publish feasible options. No order exists and nothing is spent yet.")
        demo.locator(".flex-checkout").scroll_into_view_if_needed()
        demo.wait_for_timeout(2600)
        demo.screenshot(path=str(OUT / "flex-gemini.png"), full_page=True)
        demo.get_by_role("button", name="Confirm this pickup", exact=True).click()
        expect(demo.get_by_test_id("flex-receipt")).to_be_visible()
        accepted = current(s)["bookings"][0]
        assert accepted["source"] == "gemini" and accepted["consent"]
        caption("Only this confirmation reserves resources, stock and discount budget atomically. No real payment is taken.")
        demo.wait_for_timeout(2200)
        demo.get_by_role("button", name="See what changed in the kitchen ↗").click()
        demo.get_by_test_id("flex-production-proof").scroll_into_view_if_needed()
        caption("Cooking and packing move with pickup. Existing commitments remain fixed. This is planned capacity relief, not measured sales uplift.")
        demo.wait_for_timeout(3600)
        (OUT / "flex-browser-live-receipt.json").write_text(json.dumps({"mode": "real_gemini_tools_synthetic_customer_and_kitchen", "receipt": accepted}, indent=2) + "\n")
        passed("Real Gemini tools publish choices; separate explicit customer confirmation creates a durable reservation")
        video = demo.video
        record.close()
        video.save_as(str(OUT / "flex-demo.webm"))

        s = episode(); open_session(s); quote()
        for width in (1440, 900, 390):
            page.set_viewport_size({"width": width, "height": 1040})
            for tab in ("Customer checkout", "Kitchen & evidence"):
                page.get_by_role("button", name=tab, exact=True).click()
                assert page.evaluate("document.documentElement.scrollWidth <= window.innerWidth"), f"overflow at {width} {tab}"
                if width == 390: page.screenshot(path=str(OUT / ("flex-mobile-checkout.png" if tab == "Customer checkout" else "flex-mobile-kitchen.png")), full_page=True)
        passed("Both views fit 1440, 900 and 390 pixel windows without page overflow")
        assert not errors, errors
        passed("No JavaScript page errors in any checked browser context")
        context.close(); browser.close()

    (OUT / "flex-browser-checks.json").write_text(json.dumps({"checks": checks, "javascript_errors": errors, "mode": "Real local UI/API/SQLite; one real Gemini job; synthetic restaurant; explicit injected failure"}, indent=2) + "\n")


if __name__ == "__main__": run()
