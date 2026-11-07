"""Integrated browser checks; one real model call only when --live is requested."""
import argparse
import json
import os
import re
import uuid
from pathlib import Path

from playwright.sync_api import expect, sync_playwright

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs" / "demo"


def run(live=False):
    base = os.getenv("GONDOLA_BROWSER_URL", "http://127.0.0.1:8000")
    checks, errors = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        ctx = browser.new_context(viewport={"width": 1440, "height": 1040})
        page = ctx.new_page()
        page.on("pageerror", lambda error: errors.append(str(error)))

        def start():
            with page.expect_response(lambda r: r.url.endswith("/api/demand/sessions") and r.request.method == "POST") as response:
                page.get_by_role("button", name="Start 29-order burst").click()
            assert response.value.ok
            session = response.value.json()
            expect(page.locator(".orders-plans label")).to_have_count(4)
            expect(page.get_by_role("button", name=re.compile("Apply checked plan"))).to_be_enabled()
            return session

        page.goto(base + "/rush/orders")
        expect(page).to_have_url(base + "/present/orders")
        expect(page.get_by_role("heading", name="Order manager.")).to_be_visible()
        expect(page.get_by_role("navigation", name="Present views").get_by_role("link", name="Order manager", exact=True)).to_be_visible()
        session = start()
        assert session["counts"]["pending"] == 24 and session["counts"]["accepted"] == 5
        checks.append("Present navigation and compatibility route; four channels, 29 orders, four plans")
        page.screenshot(path=str(OUT / "order-manager-inbox.png"), full_page=True)

        with page.expect_response(lambda r: r.url.endswith("/apply") and r.request.method == "POST") as response:
            page.get_by_role("button", name=re.compile("Apply checked plan")).click()
        assert response.value.ok
        applied = response.value.json()
        assert applied["session"]["counts"]["pending"] == 0
        assert applied["session"]["counts"]["declined"] == 2
        assert applied["receipt"]["action"] == "admission_plan"
        page.reload()
        expect(page.get_by_label("Resume service session")).to_have_value(session["id"])
        expect(page.locator(".orders-summary")).to_contain_text("2 declined")
        checks.append("Rules admission is atomic and reload restores decisions and receipt")

        page.get_by_role("button", name="Simulate slow fryer", exact=True).click()
        expect(page.locator(".orders-stations")).to_contain_text("0.5")
        page.get_by_role("button", name="+5 min", exact=True).click()
        expect(page.locator(".orders-summary")).to_contain_text("17:35")
        checks.append("Capacity disruption and progress update the shared plan")

        stale = start()
        prefix = base + "/api/demand/sessions/" + stale["id"]
        r = ctx.request.post(prefix + "/capacity", data={"revision": stale["revision"], "event_id": str(uuid.uuid4()), "station": "fryer", "speed": .5, "unavailable_minutes": 0})
        assert r.ok
        page.get_by_role("button", name=re.compile("Apply checked plan")).click()
        expect(page.get_by_role("alert")).to_contain_text("Kitchen state changed")
        state = ctx.request.get(prefix).json()
        assert state["counts"]["pending"] == 24
        checks.append("Stale browser plan is rejected and refreshed without admitting requests")

        if live:
            session = start()
            with page.expect_response(lambda r: r.url.endswith("/agent") and r.request.method == "POST") as response:
                page.get_by_role("button", name="Ask Order Manager to decide", exact=True).click()
            assert response.value.ok
            job_id = response.value.json()["id"]
            expect(page.get_by_test_id("order-agent-receipt")).to_be_visible(timeout=125000)
            job = ctx.request.get(base + "/api/rush/jobs/" + job_id).json()
            assert job["status"] == "done", job.get("error")
            result = job["result"]
            assert result["local_receipt_verified"] and not result["external_verified"]
            assert {e["tool"] for e in result["trace"]} == {"inspect_demand", "compare_admission_plans", "select_checked_plan"}
            state = ctx.request.get(base + "/api/demand/sessions/" + session["id"]).json()
            assert state["counts"]["pending"] == 0
            evidence = {"mode": "real_model_synthetic_orders_local_commit", "job_id": job_id,
                        "model": result["model"], "tools": [e["tool"] for e in result["trace"]],
                        "receipt": result["receipt"], "local_receipt_verified": True, "external_verified": False}
            (OUT / "order-manager-live-evidence.json").write_text(json.dumps(evidence, indent=2) + "\n", encoding="utf-8")
            page.screenshot(path=str(OUT / "order-manager-agent.png"), full_page=True)
            checks.append("Real Gemini specialist uses three tools and produces a read-back-verified local commit")

        for width in (900, 390):
            page.set_viewport_size({"width": width, "height": 1040})
            assert page.evaluate("document.documentElement.scrollWidth <= innerWidth"), width
        checks.append("Order Manager fits 900 and 390 pixel windows")
        page.set_viewport_size({"width": 1440, "height": 1040})
        for path, title in (("/present/rush", "Present"), ("/flex", "Present"), ("/past", "Past"), ("/future", "Future"), ("/review", "Review")):
            page.goto(base + path)
            expect(page.locator("header.top h1")).to_have_text(title, timeout=45000)
        checks.append("Rush, promotions/Flex and four existing workflows remain reachable")
        assert not errors, errors
        browser.close()
    data = {"checks": checks, "javascript_errors": errors, "real_model_requested": live,
            "mode": "real local browser/API; synthetic orders; no merchant writes"}
    (OUT / "order-manager-browser.json").write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(data))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--live", action="store_true")
    run(parser.parse_args().live)
