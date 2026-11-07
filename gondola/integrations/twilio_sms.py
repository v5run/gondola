"""Twilio Programmable Messaging over plain REST (no SDK)."""
from __future__ import annotations

import base64
import hashlib
import hmac

import requests

API = "https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"


class TwilioError(RuntimeError):
    pass


def send_sms(account_sid: str, auth_token: str, from_: str, to: str, body: str, status_callback: str | None = None,
             timeout: float = 10.0) -> str:
    """Send one SMS; returns the message SID."""
    data = {"From": from_, "To": to, "Body": body}
    if status_callback:
        data["StatusCallback"] = status_callback
    r = requests.post(API.format(sid=account_sid), data=data, auth=(account_sid, auth_token), timeout=timeout)
    if r.status_code >= 300:
        raise TwilioError(f"Twilio {r.status_code}")
    return r.json()["sid"]


def expected_signature(auth_token: str, url: str, params: dict) -> str:
    """Twilio request signature: HMAC-SHA1 of URL + sorted(key+value), base64."""
    s = url + "".join(f"{k}{params[k]}" for k in sorted(params))
    mac = hmac.new(auth_token.encode(), s.encode(), hashlib.sha1).digest()
    return base64.b64encode(mac).decode()


def validate_signature(auth_token: str, url: str, params: dict, signature: str) -> bool:
    """Check the X-Twilio-Signature header on an inbound webhook (POST form params)."""
    if not signature:
        return False
    return hmac.compare_digest(expected_signature(auth_token, url, params), signature)


def twiml_message(text: str) -> str:
    from xml.sax.saxutils import escape
    return f'<?xml version="1.0" encoding="UTF-8"?><Response><Message>{escape(text)}</Message></Response>'
