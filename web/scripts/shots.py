"""Screenshot screens of the built app (served by the API on :8000).

    python web/scripts/shots.py [--mock] [--size 1440x900] [--prefix tw] [--full] /present /future ...

--mock blocks /api/health so the app runs on its sample data (Backend offline banner). Prints console errors.
"""
from __future__ import annotations

import argparse
from pathlib import Path

from playwright.sync_api import sync_playwright

SHOTS = Path(__file__).resolve().parent.parent / "screenshots"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--mock", action="store_true")
    ap.add_argument("--size", default="1440x900")
    ap.add_argument("--prefix", default="tw")
    ap.add_argument("--full", action="store_true")
    ap.add_argument("--wait", type=int, default=2500)
    ap.add_argument("--click", default="", help="CSS selector to click before the shot")
    a = ap.parse_args()
    w, h = (int(x) for x in a.size.split("x"))
    SHOTS.mkdir(exist_ok=True)
    with sync_playwright() as p:
        b = p.chromium.launch(executable_path="/usr/bin/google-chrome", args=["--no-sandbox"])
        ctx = b.new_context(viewport={"width": w, "height": h}, base_url=a.base)
        if a.mock:
            ctx.route("**/api/health", lambda r: r.abort())
        page = ctx.new_page()
        errs: list[str] = []
        page.on("console", lambda m: m.type == "error" and errs.append(m.text))
        page.on("pageerror", lambda e: errs.append(str(e)))
        for path in a.paths:
            page.goto(path)
            page.wait_for_timeout(a.wait)
            if a.click:
                page.locator(a.click).first.click()
                page.wait_for_timeout(800)
            name = path.strip("/").replace("/", "-") or "home"
            out = SHOTS / f"{a.prefix}-{name}.png"
            page.screenshot(path=str(out), full_page=a.full)
            print(out)
        for e in errs:
            print("CONSOLE:", e[:300])
        b.close()


if __name__ == "__main__":
    main()
