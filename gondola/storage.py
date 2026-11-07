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

ROOT = Path(__file__).resolve().parents[1]
DAILY_TTL = 30
FINDINGS_TTL = 365
MONTHLY_TTL = 730


class Bucket:
    def __init__(self, root: Path = ROOT / "out" / "bucket", store_id: str = "hanabi-sqh"):
        self.root = root / "stores" / store_id
        self.index_path = self.root / "index.json"
        self.root.mkdir(parents=True, exist_ok=True)
        self.index = json.loads(self.index_path.read_text()) if self.index_path.exists() else {}

    def _save(self):
        self.index_path.write_text(json.dumps(self.index, indent=1))

    def put_daily(self, d: str, pdf: Path, findings: Path, created: datetime | None = None, template_version: str = "v1") -> dict:
        created = created or datetime.now()
        y, m = d[:4], d[5:7]
        dest = self.root / "daily" / y / m
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy(pdf, dest / f"{d}.pdf")
        shutil.copy(findings, dest / f"{d}.findings.json")
        rec = {"kind": "daily", "period": d, "uri": str(dest / f"{d}.pdf"), "findings": str(dest / f"{d}.findings.json"),
               "sha256": hashlib.sha256((dest / f"{d}.pdf").read_bytes()).hexdigest(), "template_version": template_version,
               "created_at": created.isoformat(), "expires_at": (created + timedelta(days=DAILY_TTL)).isoformat(), "status": "stored"}
        self.index[f"daily/{d}"] = rec
        self._save()
        return rec

    def put_monthly(self, month: str, summary: dict, created: datetime) -> dict:
        dest = self.root / "monthly"
        dest.mkdir(parents=True, exist_ok=True)
        p = dest / f"{month}.json"
        p.write_text(json.dumps(summary, indent=1, default=str))
        rec = {"kind": "monthly", "period": month, "uri": str(p), "created_at": created.isoformat(),
               "expires_at": (created + timedelta(days=MONTHLY_TTL)).isoformat(), "status": "stored"}
        self.index[f"monthly/{month}"] = rec
        self._save()
        return rec

    def apply_lifecycle(self, now: datetime) -> dict:
        """What the bucket lifecycle rule + nightly job do."""
        expired, purged = 0, 0
        for k, r in self.index.items():
            if r["kind"] != "daily":
                continue
            age = (now - datetime.fromisoformat(r["created_at"])).days
            if r["status"] in ("stored", "rebuilt") and age >= DAILY_TTL:
                Path(r["uri"]).unlink(missing_ok=True)
                r["status"] = "expired"; expired += 1
            if age >= FINDINGS_TTL and Path(r["findings"]).exists():
                Path(r["findings"]).unlink(); r["status"] = "purged"; purged += 1
        self._save()
        return {"expired": expired, "purged": purged}

    def get(self, d: str, rebuild=None, now: datetime | None = None) -> dict:
        """Signed link if stored; rebuild from findings.json if expired; monthly summary if purged."""
        r = self.index.get(f"daily/{d}")
        if r is None:
            return {"status": "not_found"}
        if r["status"] in ("stored", "rebuilt") and Path(r["uri"]).exists():
            return {"status": r["status"], "url": f"signed://{r['uri']}?ttl=900"}
        if r["status"] == "expired" and Path(r["findings"]).exists() and rebuild:
            pdf = rebuild(json.loads(Path(r["findings"]).read_text()), d)
            r["uri"], r["status"] = str(pdf), "rebuilt"
            r["created_at"] = (now or datetime.now()).isoformat()  # rebuilt copy kept 7 days
            r["created_at"] = ((now or datetime.now()) - timedelta(days=DAILY_TTL - 7)).isoformat()
            self._save()
            return {"status": "rebuilt", "url": f"signed://{pdf}?ttl=900"}
        month = d[:7]
        if f"monthly/{month}" in self.index:
            return {"status": "summary_only", "url": f"signed://{self.index[f'monthly/{month}']['uri']}?ttl=900"}
        return {"status": "gone"}

    def usage_bytes(self) -> int:
        return sum(p.stat().st_size for p in self.root.rglob("*") if p.is_file())
