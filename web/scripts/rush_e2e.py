"""Browser verification and a recorded walkthrough of the real local Rush Control app.

One live Gemini request is intentional. All restaurant/campaign data is synthetic.
"""
from __future__ import annotations

import json
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "demo"
BASE = "http://127.0.0.1:8000"


def run():
    OUT.mkdir(parents=True, exist_ok=True)
    checks, console = [], []
    def passed(name):
        checks.append(name); print("PASS", name, flush=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(viewport={"width": 1440, "height": 1080}, device_scale_factor=1)
        page = context.new_page()
        page.on("pageerror", lambda e: console.append(str(e)))
        def compare(action):
            with page.expect_response(lambda r: "/api/rush/compare" in r.url and r.request.method == "POST") as r:
                action()
            assert r.value.status == 200
            expect(page.get_by_test_id("station-timeline")).to_be_visible()
            return r.value.json()
        data = compare(lambda: page.goto(BASE + "/rush"))
        expect(page.get_by_role("heading", name="Rush control.")).to_be_visible()
        expect(page.locator(".rush-offer h4")).to_have_text("Chashu rice bowl")
        assert len(data["runs"]) == 5
        assert {o["channel"] for o in data["runs"]["coordinated"]["frames"][12]["orders"]} == {"doordash", "ubereats", "pickup"}
        expect(page.locator(".rush-offer-checks .blocked")).to_have_count(3)
        passed("Shared timeline, three channels, checked offer and five measured baselines")
        page.screenshot(path=str(OUT / "rush-overview.png"), full_page=True)

        page.locator(".rush-modebar").get_by_role("button", name="FIFO", exact=True).click()
        expect(page.locator(".rush-offer h4")).to_have_text("No active offer")
        page.locator(".rush-modebar").get_by_role("button", name="Connected control", exact=True).click()
        expect(page.locator(".rush-offer h4")).to_have_text("Chashu rice bowl")
        passed("Switching baselines changes the observed offer and reservations")

        page.get_by_label("Service minute", exact=True).fill("18")
        expect(page.locator(".rush-time strong")).to_have_text("17:48")
        page.get_by_label("Play service replay", exact=True).click()
        expect(page.locator(".rush-time strong")).not_to_have_text("17:48")
        page.get_by_label("Pause service replay", exact=True).click()
        page.get_by_label("Service minute", exact=True).fill("12")
        original = {o["id"]: o["promise"] for o in data["runs"]["coordinated"]["frames"][12]["orders"]}
        changed = compare(lambda: page.get_by_role("button", name="Delay Dashers").click())
        for o in changed["runs"]["coordinated"]["frames"][12]["orders"]:
            assert o["promise"] == original[o["id"]]
        expect(page.locator(".rush-event")).to_contain_text("original promises stay fixed")
        passed("Replay and courier revision preserve original customer promises")

        compare(lambda: page.get_by_label("Rush scenario").select_option("overload"))
        data = compare(lambda: page.get_by_label("Shared cooks").select_option("1"))
        expect(page.locator(".rush-intro-facts strong").first).to_have_text("42")
        expect(page.locator(".rush-risk")).to_be_visible()
        assert data["runs"]["coordinated"]["metrics"]["accepted"] >= 42
        passed("Overload remains visible and no accepted orders disappear")

        page.locator(".rush-settings summary").click()
        page.get_by_label("Offer budget", exact=True).fill("0")
        data = compare(lambda: page.get_by_role("button", name="Apply settings").click())
        assert all(r["metrics"]["promo_spend_cents"] == 0 for r in data["runs"].values())
        page.locator(".rush-settings summary").click()
        passed("Zero campaign budget is respected across all controllers")

        page.get_by_role("button", name="Ask the agent to act").click()
        expect(page.get_by_test_id("agent-receipt")).to_be_visible(timeout=120_000)
        expect(page.get_by_test_id("agent-receipt")).to_contain_text("Paused offers")
        expect(page.locator(".rush-tool-log")).to_contain_text("Read accepted orders")
        page.screenshot(path=str(OUT / "rush-agent-pause.png"), full_page=True)
        passed("Real Gemini refuses unsafe offers and produces a confirmed pause receipt")

        page.get_by_role("button", name="Strategy lab AI", exact=True).click()
        page.locator(".rush-history summary").click()
        saved_lab = page.locator(".rush-history button").filter(has_text="policy lab · done").first
        expect(saved_lab).to_be_visible()
        saved_lab.click()
        expect(page.get_by_test_id("lab-result")).to_be_visible()
        expect(page.get_by_test_id("lab-result")).to_contain_text("The default stays in place")
        expect(page.locator(".rush-lab-progress")).to_contain_text("independent evaluation")
        page.screenshot(path=str(OUT / "rush-policy-lab.png"), full_page=True)
        passed("Real saved policy experiment reloads with independent rejection and conventional-search comparator")

        for width in (900, 390):
            page.set_viewport_size({"width": width, "height": 1000})
            page.get_by_role("button", name="Service desk", exact=True).click()
            expect(page.get_by_test_id("station-timeline")).to_be_visible()
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), f"Overflow at {width}"
            page.screenshot(path=str(OUT / f"rush-{width}.png"), full_page=True)
        passed("Tablet and narrow browser layouts fit without page overflow")

        page.set_viewport_size({"width": 1440, "height": 1080})
        compare(lambda: page.reload())
        page.route("**/api/rush/agent", lambda route: route.fulfill(status=503, json={"detail": "Provider unavailable for browser failure test"}))
        page.get_by_role("button", name="Ask the agent to act").click()
        expect(page.get_by_role("alert")).to_contain_text("Provider unavailable")
        expect(page.get_by_test_id("agent-receipt")).to_have_count(0)
        page.unroute("**/api/rush/agent")
        passed("Provider error remains an error, with no invented successful receipt")

        offline = context.new_page()
        offline.route("**/api/rush/config", lambda route: route.abort())
        offline.goto(BASE + "/rush")
        expect(offline.get_by_role("alert")).to_be_visible()
        expect(offline.get_by_test_id("station-timeline")).to_have_count(0)
        offline.close()
        passed("Unavailable backend does not silently fabricate a simulation or AI result")
        assert not console, console
        passed("No browser JavaScript errors")

        # Record a compact, captioned walkthrough. Actions and rendered results are real.
        video_context = browser.new_context(viewport={"width": 1440, "height": 1000}, record_video_dir=str(ROOT / ".local" / "rush-video"), record_video_size={"width": 1440, "height": 1000})
        v = video_context.new_page()
        v.goto(BASE + "/rush"); v.get_by_test_id("station-timeline").wait_for()
        def caption(text):
            v.evaluate("text => { let e = document.getElementById('demo-caption'); if(!e){e=document.createElement('div'); e.id='demo-caption'; e.style.cssText='position:fixed;bottom:20px;left:120px;right:36px;z-index:9999;border:1px solid #748861;background:#173f34f5;color:#f2f5dd;padding:16px 22px;border-radius:10px;font:500 16px Inter,system-ui;box-shadow:0 6px 20px #14201c25;pointer-events:none';document.body.appendChild(e);}e.textContent=text; }", text)
        caption("Rush Control: one shared plan for orders, kitchen capacity and demand. Synthetic restaurant; real Gemini tools.")
        v.wait_for_timeout(2500)
        v.locator(".rush-stations").scroll_into_view_if_needed()
        caption("The fryer slows down. Existing orders keep their original promises; unfinished work stays assigned.")
        v.wait_for_timeout(3000)
        v.locator(".rush-offer-checks").scroll_into_view_if_needed()
        caption("Every offer uses the same reservations. Three items fail the checks; the rice bowl fits assembly capacity.")
        v.wait_for_timeout(3500)
        v.get_by_role("button", name="Ask the agent to act").click()
        caption("A real Gemini request inspects observations, checks alternatives and applies one bounded action.")
        v.get_by_test_id("agent-receipt").wait_for(timeout=120000)
        v.get_by_test_id("agent-receipt").scroll_into_view_if_needed()
        caption("The action has a tool receipt. This changes the simulated first-party menu, never a real DoorDash campaign.")
        v.wait_for_timeout(3500)
        v.locator(".rush-comparison").scroll_into_view_if_needed()
        caption("All five baselines stay visible: connected control reduces average wait here; separate campaigns earn more contribution.")
        v.wait_for_timeout(4000)
        v.get_by_role("button", name="Strategy lab AI", exact=True).click()
        v.locator(".rush-history summary").click()
        v.locator(".rush-history button").filter(has_text="policy lab · done").first.click()
        v.get_by_test_id("lab-result").wait_for()
        v.get_by_test_id("lab-result").scroll_into_view_if_needed()
        caption("The agent tested four policies. Its submission lost on unseen cases: the default stayed. No automatic promotion of a bad policy.")
        v.wait_for_timeout(4500)
        video = v.video
        video_context.close()
        video.save_as(str(OUT / "rush-demo.webm"))
        context.close(); browser.close()
    (OUT / "browser-checks.json").write_text(json.dumps({"checks": checks, "passed": len(checks), "javascript_errors": console, "real_model_calls": "One overload pause check plus one recorded intervention; other data/actions synthetic"}, indent=2), encoding="utf-8")
    print(f"{len(checks)} browser checks passed. Demo: {OUT}")


if __name__ == "__main__":
    run()
