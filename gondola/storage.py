"""Report storage with a 30-day lifecycle (local stand-in for a Cloud Storage bucket).

Layout mirrors the bucket: stores/{store}/daily/{yyyy}/{mm}/{date}.pdf (+ findings.json),
stores/{store}/monthly/{yyyy-mm}.json. A lifecycle job deletes daily PDFs older than 30 days; findings.json
(a few KB) is kept 365 days so any expired report can be rebuilt exactly from it.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path

from .paths import rel, resolve

ROOT = Path(__file__).resolve().parents[1]
DAILY_TTL = 30
FINDINGS_TTL = 365
MONTHLY_TTL = 730


class Bucket:
    def __init__(self, root: Path = ROOT / "out" / "bucket", store_id: str = "hanabi-sqh"):
        self.root = root / "stores" / store_id
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = json.loads(self.index_path.read_text(encoding="utf-8")) if self.index_path.exists() else {}

    def path(self, stored: str | None) -> Path | None:
        """Real path of a stored uri (relative to this store's folder; old absolute paths are rebased)."""
        return resolve(stored, self.root, anchor=f"/stores/{self.root.name}/")

    def _save(self):
        self.index_path.write_text(json.dumps(self.index, indent=1), encoding="utf-8")

    def put_daily(self, d: str, pdf: Path | None, findings: Path, created: datetime | None = None, template_version: str = "v1",
                  html: Path | None = None) -> dict:
        """Store one night's report. `pdf` may not exist yet (the history backfill renders PDFs in one batch at the end,
        see attach_pdf); the record is then stored with sha256 None until the PDF arrives."""
        created = created or datetime.now()
        y, m = d[:4], d[5:7]
        dest = self.root / "daily" / y / m
        dest.mkdir(parents=True, exist_ok=True)
        has_pdf = pdf is not None and Path(pdf).exists()
        if has_pdf and Path(pdf).resolve() != (dest / f"{d}.pdf").resolve():
            shutil.copy(pdf, dest / f"{d}.pdf")
        shutil.copy(findings, dest / f"{d}.findings.json")
        if html is not None and Path(html).exists():
            shutil.copy(html, dest / f"{d}.html")
        rec = {"kind": "daily", "period": d, "uri": rel(dest / f"{d}.pdf", self.root), "findings": rel(dest / f"{d}.findings.json", self.root),
               "html": rel(dest / f"{d}.html", self.root) if (dest / f"{d}.html").exists() else None,
               "sha256": hashlib.sha256((dest / f"{d}.pdf").read_bytes()).hexdigest() if has_pdf else None,
               "template_version": template_version,
               "created_at": created.isoformat(), "expires_at": (created + timedelta(days=DAILY_TTL)).isoformat(), "status": "stored"}
        self.index[f"daily/{d}"] = rec
        self._save()
        return rec

    def pdf_dest(self, key: str) -> Path:
        """Where the PDF of an index record lives in the bucket."""
        return self.path(self.index[key]["uri"])

    def attach_pdf(self, key: str, pdf: Path | None = None) -> dict:
        """Record a PDF rendered after put_daily/put_monthly (at the record's uri, or copied from `pdf`)."""
        r = self.index[key]
        dest = self.path(r["uri"])
        if pdf is not None and Path(pdf).resolve() != dest.resolve():
            shutil.copy(pdf, dest)
        r["sha256"] = hashlib.sha256(dest.read_bytes()).hexdigest()
        self._save()
        return r

    def put_monthly(self, month: str, summary: dict, created: datetime, html: Path | None = None,
                    pdf: Path | None = None) -> dict:
        """Monthly summary JSON (kept 730 days), plus the rendered monthly report (HTML, and PDF if given or attached
        later with attach_pdf)."""
        dest = self.root / "monthly"
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / f"{month}.json"
        p.write_text(json.dumps(summary, indent=1, default=str), encoding="utf-8")
        if html is not None and Path(html).exists() and Path(html).resolve() != (dest / f"{month}.html").resolve():
            shutil.copy(html, dest / f"{month}.html")
        has_pdf = pdf is not None and Path(pdf).exists()
        if has_pdf and Path(pdf).resolve() != (dest / f"{month}.pdf").resolve():
            shutil.copy(pdf, dest / f"{month}.pdf")
        rec = {"kind": "monthly", "period": month, "summary": rel(p, self.root), "uri": rel(dest / f"{month}.pdf", self.root),
               "html": rel(dest / f"{month}.html", self.root) if (dest / f"{month}.html").exists() else None,
               "sha256": hashlib.sha256((dest / f"{month}.pdf").read_bytes()).hexdigest() if (dest / f"{month}.pdf").exists() else None,
               "created_at": created.isoformat(), "expires_at": (created + timedelta(days=MONTHLY_TTL)).isoformat(), "status": "stored"}
        self.index[f"monthly/{month}"] = rec
        self._save()
        return rec

    def monthly_summary(self, month: str) -> dict | None:
        r = self.index.get(f"monthly/{month}")
        if not r:
            return None
        p = self.path(r.get("summary") or r["uri"])  # older records kept the summary JSON at uri
        return json.loads(p.read_text(encoding="utf-8")) if p and p.exists() and p.suffix == ".json" else None

    def apply_lifecycle(self, now: datetime) -> dict:
        """What the bucket lifecycle rule + nightly job do."""
        expired, purged = 0, 0
        for k, r in self.index.items():
            if r["kind"] != "daily":
                continue
            age = (now - datetime.fromisoformat(r["created_at"])).days
            if r["status"] in ("stored", "rebuilt") and age >= DAILY_TTL:
                self.path(r["uri"]).unlink(missing_ok=True)
                if r.get("html"):
                    self.path(r["html"]).unlink(missing_ok=True)
                r["status"] = "expired"; expired += 1
            if age >= FINDINGS_TTL and self.path(r["findings"]).exists():
                self.path(r["findings"]).unlink(); r["status"] = "purged"; purged += 1
        self._save()
        return {"expired": expired, "purged": purged}

    def get(self, d: str, rebuild=None, now: datetime | None = None) -> dict:
        """Signed link if stored; rebuild from findings.json if expired; monthly summary if purged.
        rebuild(ctx, d) -> path of the rebuilt PDF; an HTML file next to it (same stem) is kept too."""
        r = self.index.get(f"daily/{d}")
        if r is None:
            return {"status": "not_found"}
        if r["status"] in ("stored", "rebuilt") and self.path(r["uri"]).exists():
            return {"status": r["status"], "url": f"signed://{r['uri']}?ttl=900"}
        if r["status"] in ("expired", "stored", "rebuilt") and self.path(r["findings"]).exists() and rebuild:
            built = Path(rebuild(json.loads(self.path(r["findings"]).read_text(encoding="utf-8")), d))
            dest = self.root / "daily" / d[:4] / d[5:7]
            dest.mkdir(parents=True, exist_ok=True)
            pdf = dest / f"{d}.pdf"
            if built.resolve() != pdf.resolve():
                shutil.copy(built, pdf)  # keep the rebuilt copy inside the bucket, stored as a relative uri
            h = built.with_suffix(".html")
            if h.exists() and h.resolve() != (dest / f"{d}.html").resolve():
                shutil.copy(h, dest / f"{d}.html")
            r["uri"], r["status"] = rel(pdf, self.root), "rebuilt"
            r["html"] = rel(dest / f"{d}.html", self.root) if (dest / f"{d}.html").exists() else r.get("html")
            r["sha256"] = hashlib.sha256(pdf.read_bytes()).hexdigest()
            # a rebuilt copy is kept 7 days: back-date created_at so the 30-day rule removes it then
            r["created_at"] = ((now or datetime.now()) - timedelta(days=DAILY_TTL - 7)).isoformat()
            r["expires_at"] = ((now or datetime.now()) + timedelta(days=7)).isoformat()
            r["rebuilt_at"] = (now or datetime.now()).isoformat(timespec="seconds")
            self._save()
            return {"status": "rebuilt", "url": f"signed://{r['uri']}?ttl=900"}
        month = d[:7]
        if f"monthly/{month}" in self.index:
            m = self.index[f"monthly/{month}"]
            return {"status": "summary_only", "url": f"signed://{m.get('summary') or m['uri']}?ttl=900"}
        return {"status": "gone"}

    def usage_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
