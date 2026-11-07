"""Report Agent renderer: findings -> HTML -> PDF (headless Chromium via Playwright)."""
from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

TEMPLATES = Path(__file__).parent / "templates"
CHROME = os.getenv("CHROME_PATH", "/usr/bin/google-chrome")


def curve_svg(today: list[float], usual: list[float], w: int = 300, h: int = 120) -> str:
    n = max(len(today), len(usual), 1)
    top = max(max(today, default=1), max(usual, default=1)) * 1.1
    def path(vals):
        pts = [f"{i * w / (n - 1):.1f},{h - v / top * h:.1f}" for i, v in enumerate(vals)]
        return "M" + " L".join(pts)
    return (f'<svg viewBox="0 0 {w} {h + 4}" width="100%"><path d="{path(usual)}" fill="none" stroke="#c9ccc6" stroke-width="2"/>'
            f'<path d="{path(today)}" fill="none" stroke="#0f4d40" stroke-width="2.4"/></svg>')


def render_html(ctx: dict, template: str = "daily.html") -> str:
    env = Environment(loader=FileSystemLoader(TEMPLATES), autoescape=True)
    return env.get_template(template).render(**ctx)


async def _pdf(html_path: Path, pdf_path: Path):
    from playwright.async_api import async_playwright
    async with async_playwright() as p:
        b = await p.chromium.launch(executable_path=CHROME, args=["--no-sandbox"])
        pg = await b.new_page()
        await pg.goto(html_path.as_uri())
        await pg.pdf(path=str(pdf_path), format="Letter", print_background=True,
                     margin={"top": "0", "bottom": "0", "left": "0", "right": "0"})
        await b.close()


def render_report(ctx: dict, out_dir: Path, name: str) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    html = render_html(ctx)
    hp = out_dir / f"{name}.html"
    hp.write_text(html)
    pp = out_dir / f"{name}.pdf"
    asyncio.run(_pdf(hp, pp))
    (out_dir / f"{name}.findings.json").write_text(json.dumps(ctx, default=str, indent=1))
    return {"html": str(hp), "pdf": str(pp), "bytes": pp.stat().st_size, "rendered_at": datetime.now().isoformat()}
