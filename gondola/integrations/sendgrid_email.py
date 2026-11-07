"""SendGrid v3 mail send, with the Daily Close Report attached."""
from __future__ import annotations

import base64
from pathlib import Path

import requests

API = "https://api.sendgrid.com/v3/mail/send"


class SendGridError(RuntimeError):
    pass


def build_payload(from_: str, to: list[str], subject: str, body: str, attachment: str | Path | None = None) -> dict:
    payload = {
        "personalizations": [{"to": [{"email": t} for t in to]}],
        "from": {"email": from_, "name": "Gondola"},
        "subject": subject,
        "content": [{"type": "text/plain", "value": body}],
    }
    if attachment:
        p = Path(attachment)
        if p.exists():
            payload["attachments"] = [{"content": base64.b64encode(p.read_bytes()).decode(), "type": "application/pdf",
                                       "filename": p.name, "disposition": "attachment"}]
    return payload


def send_email(api_key: str, from_: str, to: list[str], subject: str, body: str, attachment: str | Path | None = None,
               timeout: float = 15.0) -> str:
    """Returns SendGrid's X-Message-Id (or 'accepted')."""
    r = requests.post(API, json=build_payload(from_, to, subject, body, attachment),
                      headers={"Authorization": f"Bearer {api_key}"}, timeout=timeout)
    if r.status_code >= 300:
        raise SendGridError(f"SendGrid {r.status_code}")
    return r.headers.get("X-Message-Id", "accepted")
