"""Sentinel Agent tools: who needs to know, and how fast?

Rules decide urgency (the LLM may only write the wording). Urgent -> SMS now; important -> email/report;
FYI -> dashboard. Quiet hours 1-8 am except failures. One message per issue (dedupe key).
Adapters send through Twilio / SendGrid only if credentials exist; otherwise they write to out/outbox.jsonl.
"""
from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime
from pathlib import Path

from .. import clock

ROOT = Path(__file__).resolve().parents[2]
URGENT, IMPORTANT, FYI = "urgent", "important", "fyi"
DD_CANCEL_GOAL = 0.011


def score_urgency(f: dict) -> str:
    k = f.get("kind", "")
    amt = abs(f.get("impact_usd") or 0)
    if k == "close_failed":
        return URGENT
    if k == "payout_short" and f.get("fresh", True) and (f.get("recoverable_usd") or 0) >= 75:
        return URGENT  # disputes have a 14-day window: smaller amounts go in the email and the weekly digest
    if k == "cash_short" and amt > 20:
        return URGENT
    if k == "cancel_rate" and f.get("rate", 0) >= DD_CANCEL_GOAL and f.get("prev_rate", 1) < DD_CANCEL_GOAL:
        return URGENT  # text when the rate crosses the goal, not every night it stays there
    if k == "sold_out_tonight" and (f.get("app_cancels") or 0) >= 5:
        return URGENT
    if k == "drawer_not_closed":
        return IMPORTANT
    if k == "runout_before_rush":
        return URGENT
    if k in ("payout_short", "cash_short", "usage_variance", "commission_overcharge", "labour_high", "error_charge_disputable",
             "cancel_rate", "sold_out_tonight"):
        return IMPORTANT
    return FYI


def in_quiet_hours(ts: datetime) -> bool:
    return 1 <= ts.hour < 8


class Notifier:
    def __init__(self, outbox: Path = ROOT / "out" / "outbox.jsonl", sms_to: list[str] | None = None,
                 email_to: list[str] | None = None, opted_in: bool = True):
        self.outbox = outbox
        outbox.parent.mkdir(parents=True, exist_ok=True)
        self.sms_to = sms_to or ["+1-412-555-0142 (manager)"]
        self.email_to = email_to or ["owner@hanabiramen.example"]
        self.opted_in = opted_in
        self.sent: dict[str, dict] = {}  # key -> the record first written for it
        if outbox.exists():
            for line in outbox.read_text(encoding="utf-8").splitlines():
                try:
                    r = json.loads(line)
                except ValueError:
                    continue
                self.sent.setdefault(r.get("key"), r)
        from ..config import get_settings
        self.settings = get_settings()
        self.sms_live = self.settings.twilio_live
        self.email_live = self.settings.sendgrid_live
        self.live = self.sms_live and self.email_live
        if self.sms_live and sms_to is None:
            self.sms_to = self.settings.alert_sms_to
        if self.email_live and email_to is None:
            self.email_to = self.settings.alert_email_to

    def _deliver_sms(self, body: str) -> tuple[str, list]:
        """Send through Twilio when configured; otherwise a dry run. Returns (status, provider ids)."""
        if not self.sms_live:
            return "dry_run", []
        from ..integrations import twilio_sms
        s, ids = self.settings, []
        cb = f"{s.public_base_url.rstrip('/')}/api/sms/status" if s.public_base_url else None
        try:
            for to in self.sms_to:
                ids.append(twilio_sms.send_sms(s.twilio_account_sid, s.twilio_auth_token, s.twilio_from, to, body, cb))
            return "sent", ids
        except Exception as e:  # noqa: BLE001 - never let a provider error break the close
            return f"failed: {e}"[:200], ids

    def _deliver_email(self, subject: str, body: str, attachment: str | None) -> tuple[str, str | None]:
        if not self.email_live:
            return "dry_run", None
        from ..integrations import sendgrid_email
        s = self.settings
        try:
            return "sent", sendgrid_email.send_email(s.sendgrid_api_key, s.alert_email_from, self.email_to, subject, body, attachment)
        except Exception as e:  # noqa: BLE001
            return f"failed: {e}"[:200], None

    @property
    def sent_keys(self) -> set:
        return set(self.sent)

    def _suppressed(self, key: str) -> dict:
        o = self.sent.get(key) or {}
        return {"status": "duplicate_suppressed", "key": key, "channel": o.get("channel"), "body": o.get("body"),
                "subject": o.get("subject"), "sent_at": o.get("ts"), "ts": o.get("ts"), "original_status": o.get("status")}

    def _write(self, rec: dict):
        with self.outbox.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec) + "\n")

    def send_sms(self, key: str, body: str, ts: datetime, failure: bool = False) -> dict:
        if not self.opted_in:
            return {"status": "blocked_no_opt_in"}
        if key in self.sent:
            return self._suppressed(key)
        if in_quiet_hours(ts) and not failure:
            rec = {"key": key, "channel": "sms", "to": self.sms_to, "body": body, "status": "held_for_8am", "ts": ts.isoformat()}
        else:
            if len(body) > 320:
                body = body[:317] + "..."
            body = body + " Reply STOP to opt out."
            status, ids = self._deliver_sms(body)
            rec = {"key": key, "channel": "sms", "to": self.sms_to, "body": body, "status": status, "ts": ts.isoformat()}
            if ids:
                rec["provider_ids"] = ids
        self._write(rec); self.sent[key] = rec
        return rec

    def send_email(self, key: str, subject: str, body: str, attachment: str | None, ts: datetime,
                   stored_attachment: str | None = None) -> dict:
        """attachment: real path sent to the provider. stored_attachment: what the outbox records (a relative path)."""
        if key in self.sent:
            return self._suppressed(key)
        status, mid = self._deliver_email(subject, body, attachment)
        rec = {"key": key, "channel": "email", "to": self.email_to, "subject": subject, "body": body,
               "attachment": stored_attachment if stored_attachment is not None else (Path(attachment).name if attachment else None),
               "status": status, "ts": ts.isoformat()}
        if mid:
            rec["provider_id"] = mid
        self._write(rec); self.sent[key] = rec
        return rec


def dedupe_key(store_id: str, date: str, f: dict) -> str:
    return hashlib.sha1(f"{store_id}|{date}|{f.get('kind')}|{f.get('channel')}|{f.get('sku')}|{f.get('for_date')}".encode()).hexdigest()[:16]


def sms_text(f: dict) -> str:
    """Template wording. With an LLM attached, the Report/Sentinel agent may rephrase, but every number is
    passed through unchanged and checked afterwards (see agents.guardrails)."""
    k = f["kind"]
    if k == "payout_short":
        return f"Gondola: {f['channel_name']} paid ${f['impact_usd']:,.2f} less than expected for {f['for_date']} ({f['detail']}). Dispute checklist ready."
    if k == "cash_short":
        return f"Gondola: cash drawer was ${f['impact_usd']:,.2f} short tonight (expected ${f['expected']:,.2f}, counted ${f['counted']:,.2f})."
    if k == "runout_before_rush":
        return f"Gondola: chashu will run out around {clock(f['time'])} tomorrow at the current prep. Plan suggests {f['par']} portions."
    if k == "cancel_rate":
        return f"Gondola: DoorDash 7-day cancellation rate is {f['rate']:.1%} (goal under 1.1%)."
    if k == "close_failed":
        return f"Gondola: tonight's close didn't finish ({f['detail']}). We'll retry at 5 am."
    return f"Gondola: {f.get('title', k)}"


def short_text(f: dict) -> str:
    k = f["kind"]
    if k == "payout_short":
        n = f.get("n_disputable", 0)
        return (f"{f['channel_name']} {f['for_date'][:3]}: ${f['recoverable_usd']:,.2f} looks recoverable "
                f"({n} charge{'s' if n != 1 else ''} to dispute)")
    if k == "cash_short":
        return f"Cash drawer ${f['impact_usd']:,.2f} short"
    if k == "runout_before_rush":
        return f"Chashu runs out ~{clock(f['time'])} tomorrow at usual prep; plan says {f['par']}"
    if k == "cancel_rate":
        return f"DoorDash store-caused cancellations {f['rate']:.1%} over 7 days (goal under 1.1%)"
    if k == "sold_out_tonight":
        return f"Chashu sold out {f['at'].lower()}, still live on apps {f['minutes_live']} min ({f['app_cancels']} cancels)"
    return f.get("title", k)


def bundle_sms(texts: list[str], date_label: str) -> str:
    """One text per close, not one per finding: managers ignore a stream of alerts."""
    items = [t.replace("Gondola: ", "") for t in texts]
    head = f"Gondola close {date_label}: {len(items)} thing{'s' if len(items) != 1 else ''} need{'s' if len(items) == 1 else ''} you."
    body = " ".join(f"{i}) {t}" for i, t in enumerate(items[:3], 1))
    more = f" +{len(items) - 3} more in the report." if len(items) > 3 else ""
    return f"{head} {body}{more} Reply with a number for details."
