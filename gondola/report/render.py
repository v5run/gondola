"""Report Agent renderer: findings -> HTML -> PDF (headless Chromium via Playwright)."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).parent / "templates"
# Browser for HTML -> PDF. Order: CHROME_PATH (if it exists) -> Playwright's bundled Chromium
# (`python -m playwright install chromium`) -> an installed Chrome / Edge channel -> common system paths.
SYSTEM_BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
]
INSTALL_HINT = "No browser for PDF rendering. Run `python -m playwright install chromium` (or set CHROME_PATH)."


def chrome_path() -> str | None:
    """CHROME_PATH from the environment, if it points at a file; else None (use Playwright's bundled Chromium)."""
    p = os.getenv("CHROME_PATH", "").strip().strip('"')
    return p if p and Path(p).is_file() else None


async def _launch(p):
    explicit = chrome_path()
    if explicit:
        return await p.chromium.launch(executable_path=explicit, args=["--no-sandbox"])
    errors = []
    for kw in ({}, {"channel": "chrome"}, {"channel": "msedge"}):
        try:
            return await p.chromium.launch(args=["--no-sandbox"], **kw)
        except Exception as e:  # noqa: BLE001 - try the next option
            errors.append(str(e).splitlines()[0] if str(e) else type(e).__name__)
    for path in SYSTEM_BROWSERS:
        if Path(path).is_file():
            return await p.chromium.launch(executable_path=path, args=["--no-sandbox"])
    raise RuntimeError(INSTALL_HINT + " Tried: " + " | ".join(errors))


def curve_svg(today: list[float], usual: list[float], w: int = 300, h: int = 120) -> str:
    n = max(len(today), len(usual), 1)
    top = max(max(today, default=1), max(usual, default=1)) * 1.1
    def path(vals):
        pts = [f"{i * w / (n - 1):.1f},{h - v / top * h:.1f}" for i, v in enumerate(vals)]
        return "M" + " L".join(pts)
    return (f'<svg viewBox="0 0 {w} {h + 4}" width="100%"><path d="{path(usual)}" fill="none" stroke="#c9ccc6" stroke-width="2"/>'
            f'<path d="{path(today)}" fill="none" stroke="#0f4d40" stroke-width="2.4"/></svg>')


FONTS = Path(__file__).parent / "fonts"


def font_face() -> str:
    """Inter (OFL, latin subset, variable weight) embedded as a data URI, so the HTML and PDF look the same on any
    machine and offline. Falls back to the system font stack if the file is missing."""
    f = FONTS / "inter-latin-wght-normal.woff2"
    if not f.exists():
        return ""
    import base64
    b64 = base64.b64encode(f.read_bytes()).decode()
    return ("@font-face { font-family: 'Inter'; font-style: normal; font-weight: 100 900; font-display: block; "
            f"src: url(data:font/woff2;base64,{b64}) format('woff2'); }}")


def render_html(ctx: dict, template: str = "daily.html") -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    return env.get_template(template).render(**{"font_face": font_face(), **ctx})


async def _pdf(html_path: Path, pdf_path: Path):
    await _pdf_many([(html_path, pdf_path)])


async def _pdf_many(jobs: list[tuple[Path, Path]], concurrency: int = 4):
    """Print many HTML files with ONE browser, a few pages at a time (launching Chromium costs ~1 s; a page ~0.3 s)."""
    from playwright.async_api import async_playwright
    if not jobs:
        return
    async with async_playwright() as p:
        b = await _launch(p)
        try:
            sem = asyncio.Semaphore(max(1, concurrency))

            async def one(hp: Path, pp: Path):
                async with sem:
                    pg = await b.new_page()
                    try:
                        await pg.goto(Path(hp).resolve().as_uri())
                        Path(pp).parent.mkdir(parents=True, exist_ok=True)
                        await pg.pdf(path=str(pp), format="Letter", print_background=True,
                                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
                    finally:
                        await pg.close()
            await asyncio.gather(*(one(h, q) for h, q in jobs))
        finally:
            await b.close()


def render_pdfs(jobs: list[tuple[Path, Path]], concurrency: int = 4) -> int:
    """Synchronous wrapper: render (html, pdf) pairs in one browser session. Returns how many were printed."""
    jobs = [(Path(h), Path(q)) for h, q in jobs]
    if not jobs:
        return 0
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        asyncio.run(_pdf_many(jobs, concurrency))
        return len(jobs)
    import threading  # called from inside an event loop: run in a helper thread with its own loop
    err: list = []
    t = threading.Thread(target=lambda: _run_capture(err, jobs, concurrency))
    t.start(); t.join()
    if err:
        raise err[0]
    return len(jobs)


def _run_capture(err: list, jobs, concurrency):
    try:
        asyncio.run(_pdf_many(jobs, concurrency))
    except Exception as e:  # noqa: BLE001
        err.append(e)


# When a list, render_report writes the HTML and findings.json but queues the PDF here instead of printing it
# (the history backfill prints all queued PDFs in one browser session at the end).
DEFER_PDF: list | None = None


def render_report(ctx: dict, out_dir: Path, name: str, template: str = "daily.html") -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_html(ctx, template)
    hp = out_dir / f"{name}.html"
    hp.write_text(html, encoding="utf-8")
    pp = out_dir / f"{name}.pdf"
    (out_dir / f"{name}.findings.json").write_text(json.dumps(ctx, default=str, indent=1), encoding="utf-8")
    if DEFER_PDF is not None:
        pp.unlink(missing_ok=True)
        DEFER_PDF.append((hp, pp))
        return {"html": str(hp), "pdf": str(pp), "bytes": None, "rendered_at": None, "deferred": True}
    render_pdfs([(hp, pp)])
    return {"html": str(hp), "pdf": str(pp), "bytes": pp.stat().st_size, "rendered_at": datetime.now().isoformat()}


# ------------------------------------------------------------------ monthly report
def bars_svg(values: list[float], labels: list[str], marks: dict[int, str] | None = None, w: int = 640, h: int = 150) -> str:
    """Daily sales bars for the monthly report. marks: {index: "best"|"worst"|"closed"|"soldout"} recolour a bar."""
    marks = marks or {}
    n = max(len(values), 1)
    top = max(max(values, default=1), 1) * 1.08
    bw = w / n
    out = [f'<svg viewBox="0 0 {w} {h + 18}" width="100%" role="img" aria-label="Net sales per day">']
    for i, v in enumerate(values):
        bh = v / top * h
        col = {"best": "#0f4d40", "worst": "#d03b3b", "closed": "#e4e1d9"}.get(marks.get(i), "#7fa89b")
        out.append(f'<rect x="{i * bw + 1.5:.1f}" y="{h - bh:.1f}" width="{max(bw - 3, 1):.1f}" height="{max(bh, 0.5):.1f}" rx="2" fill="{col}"/>')
        if marks.get(i) == "soldout":
            out.append(f'<circle cx="{i * bw + bw / 2:.1f}" cy="{h - bh - 5:.1f}" r="2.4" fill="#e0a526"/>')
        if labels[i] and (i % 5 == 0 or i == n - 1):
            out.append(f'<text x="{i * bw + bw / 2:.1f}" y="{h + 13}" font-size="9" text-anchor="middle" fill="#8b938e">{labels[i]}</text>')
    out.append("</svg>")
    return "".join(out)


def render_monthly(ctx: dict, out_dir: Path, name: str, pdf: bool = True) -> dict:
    """Monthly summary report (2 pages, same design as the daily). Returns {html, pdf}; with DEFER_PDF set the PDF is
    queued like the daily ones."""
    out_dir.mkdir(parents=True, exist_ok=True)
    hp = out_dir / f"{name}.html"
    hp.write_text(render_html(ctx, "monthly.html"), encoding="utf-8")
    pp = out_dir / f"{name}.pdf"
    if not pdf:
        return {"html": str(hp), "pdf": None}
    if DEFER_PDF is not None:
        pp.unlink(missing_ok=True)
        DEFER_PDF.append((hp, pp))
        return {"html": str(hp), "pdf": str(pp), "deferred": True}
    render_pdfs([(hp, pp)])
    return {"html": str(hp), "pdf": str(pp)}
