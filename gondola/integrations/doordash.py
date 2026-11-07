"""DoorDash item status (pause one item on DoorDash only), via the Marketplace API.

All merchant writes are disabled, even with credentials. AppPauseExecutor logs dry runs.
Partner access and authenticated, action-bound manager approval are needed before live use.
"""
from __future__ import annotations

import base64
import hashlib
import json
import time
from datetime import datetime
from pathlib import Path

import jwt
import requests

from ..config import ROOT, Settings, get_settings

BASE = "https://openapi.doordash.com"


def make_jwt(developer_id: str, key_id: str, signing_secret: str, ttl_s: int = 300, now: int | None = None) -> str:
    """DoorDash JWT: HS256, header dd-ver DD-JWT-V1, secret is base64url-encoded."""
    now = int(now or time.time())
    secret = base64.urlsafe_b64decode(signing_secret + "=" * (-len(signing_secret) % 4))
    claims = {"aud": "doordash", "iss": developer_id, "kid": key_id, "iat": now, "exp": now + ttl_s}
    return jwt.encode(claims, secret, algorithm="HS256", headers={"dd-ver": "DD-JWT-V1"})


class DoorDashClient:
    def __init__(self, s: Settings | None = None, session: requests.Session | None = None):
        self.s = s or get_settings()
        self.http = session or requests.Session()

    @property
    def live(self) -> bool:
        return self.s.doordash_live

    def set_item_status(self, store_id: str, item_id: str, active: bool) -> dict:
        # There is no authenticated, action-bound manager approval service yet.
        # Credentials or a demo approval must never grant write authority.
        raise RuntimeError("Live merchant writes are disabled pending authenticated manager approval")


class AppPauseExecutor:
    """What Guard calls to pause/unpause an item per app. Idempotent; always logs to out/actions_log.jsonl.
    Merchant actions are always dry runs, including when credentials or clients are supplied."""

    def __init__(self, log_path: Path = ROOT / "out" / "actions_log.jsonl", s: Settings | None = None,
                 doordash: DoorDashClient | None = None, square=None, square_variation_ids: dict | None = None,
                 square_all_channels: bool = False):
        self.s = s or get_settings()
        self.log_path = log_path
        log_path.parent.mkdir(parents=True, exist_ok=True)
        self.dd = doordash or DoorDashClient(self.s)
        self.square = square
        self.square_ids = square_variation_ids or {}
        self.square_all = square_all_channels
        self.seen = set()
        if log_path.exists():
            for line in log_path.read_text(encoding="utf-8").splitlines():
                try:
                    self.seen.add(json.loads(line)["key"])
                except (ValueError, KeyError):
                    pass

    def _log(self, rec: dict) -> dict:
        with self.log_path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")
        self.seen.add(rec["key"])
        return rec

    def pause(self, store_id: str, date: str, item: str, app: str, active: bool = False, at: str | None = None) -> dict:
        key = hashlib.sha1(f"{store_id}|{date}|{item}|{app}|{active}".encode()).hexdigest()[:16]
        if key in self.seen:
            return {"key": key, "status": "duplicate_ignored"}
        rec = {"key": key, "store": store_id, "date": date, "item": item, "app": app, "active": active,
               "at": at or datetime.now().strftime("%H:%M"), "action": "set_item_status"}
        # Even injected clients must not bypass the demo's write boundary.
        rec["status"] = "dry_run"
        return self._log(rec)
