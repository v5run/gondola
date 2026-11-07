"""Integration adapters, all offline (requests-mock / monkeypatch)."""
import base64
import json
import sys
from datetime import datetime
from pathlib import Path

import jwt
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from gondola import config  # noqa: E402
from gondola.integrations import doordash, llm, sendgrid_email, square, twilio_sms  # noqa: E402
from gondola.tools import sentinel  # noqa: E402

ENV_KEYS = ["GONDOLA_AGENTS", "TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_FROM", "ALERT_SMS_TO", "SENDGRID_API_KEY",
            "ALERT_EMAIL_FROM", "ALERT_EMAIL_TO", "GOOGLE_API_KEY", "ANTHROPIC_API_KEY", "SQUARE_ACCESS_TOKEN",
            "SQUARE_LOCATION_ID", "DOORDASH_DEVELOPER_ID", "DOORDASH_KEY_ID", "DOORDASH_SIGNING_SECRET", "DOORDASH_STORE_ID"]


@pytest.fixture
def clean_env(monkeypatch):
    for k in ENV_KEYS:
        monkeypatch.setenv(k, "")  # empty overrides anything in a local .env
    return monkeypatch


def test_status_offline(clean_env):
    st = config.integrations_status()
    assert set(st) == {"twilio", "sendgrid", "llm", "square", "doordash", "agents"}
    assert not any(v["live"] for v in st.values())


def test_status_live(clean_env):
    for k, v in {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM": "+14165550100",
                 "ALERT_SMS_TO": "+14165550101", "GOOGLE_API_KEY": "g"}.items():
        clean_env.setenv(k, v)
    st = config.integrations_status()
    assert st["twilio"]["live"] and st["llm"]["provider"] == "gemini" and not st["sendgrid"]["live"]


def test_twilio_payload_and_auth(requests_mock):
    m = requests_mock.post("https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json", json={"sid": "SM123"})
    sid = twilio_sms.send_sms("AC1", "tok", "+14165550100", "+14165550101", "Gondola close: cash $23.50 short")
    assert sid == "SM123"
    req = m.last_request
    assert "Body=Gondola+close" in req.text and "To=%2B14165550101" in req.text
    assert req.headers["Authorization"] == "Basic " + base64.b64encode(b"AC1:tok").decode()


def test_twilio_signature_roundtrip():
    params = {"From": "+14165550101", "Body": "why"}
    sig = twilio_sms.expected_signature("tok", "https://x.test/api/sms/inbound", params)
    assert twilio_sms.validate_signature("tok", "https://x.test/api/sms/inbound", params, sig)
    assert not twilio_sms.validate_signature("tok", "https://x.test/api/sms/inbound", {**params, "Body": "x"}, sig)
    assert "<Message>a &amp; b</Message>" in twilio_sms.twiml_message("a & b")


def test_sendgrid_payload_with_pdf(tmp_path, requests_mock):
    pdf = tmp_path / "2026-11-05.pdf"; pdf.write_bytes(b"%PDF-1.4 demo")
    m = requests_mock.post(sendgrid_email.API, status_code=202, headers={"X-Message-Id": "abc"})
    mid = sendgrid_email.send_email("SG.key", "gondola@x.com", ["o@x.com"], "Daily Close Report", "body", pdf)
    body = m.last_request.json()
    assert mid == "abc" and body["attachments"][0]["filename"] == "2026-11-05.pdf"
    assert base64.b64decode(body["attachments"][0]["content"]) == b"%PDF-1.4 demo"
    assert m.last_request.headers["Authorization"] == "Bearer SG.key"


def test_notifier_credentials_still_dry_run(clean_env, tmp_path, requests_mock):
    for k, v in {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM": "+14165550100",
                 "ALERT_SMS_TO": "+14165550101,+14165550102"}.items():
        clean_env.setenv(k, v)
    m = requests_mock.post("https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json", json={"sid": "SM1"})
    n = sentinel.Notifier(tmp_path / "o.jsonl")
    r = n.send_sms("k1", "Gondola close Thu Nov 5: cash $23.50 short", datetime(2026, 11, 5, 23, 10))
    assert r["status"] == "dry_run" and m.call_count == 0
    assert json.loads((tmp_path / "o.jsonl").read_text(encoding="utf-8").splitlines()[0])["status"] == "dry_run"
    # quiet hours: held, not sent
    r2 = n.send_sms("k2", "x", datetime(2026, 11, 6, 2, 0))
    assert r2["status"] == "held_for_8am" and m.call_count == 0


def test_notifier_does_not_call_provider_with_credentials(clean_env, tmp_path, requests_mock):
    for k, v in {"TWILIO_ACCOUNT_SID": "AC1", "TWILIO_AUTH_TOKEN": "t", "TWILIO_FROM": "+1", "ALERT_SMS_TO": "+2"}.items():
        clean_env.setenv(k, v)
    requests_mock.post("https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json", status_code=400, text="bad")
    r = sentinel.Notifier(tmp_path / "o.jsonl").send_sms("k", "hi", datetime(2026, 11, 5, 23))
    assert r["status"] == "dry_run"


def test_phrase_guardrail_fallback(monkeypatch):
    facts = {"cash_short": 23.50, "recoverable": 86.40}
    tmpl = "Cash drawer $23.50 short; $86.40 looks recoverable."
    monkeypatch.setattr(llm, "complete", lambda p, s=None: "Drawer came up $25 short and $86.40 is recoverable.")
    assert llm.phrase(facts, tmpl) == tmpl  # invented number -> template
    monkeypatch.setattr(llm, "complete", lambda p, s=None: "Heads up: the drawer is $23.50 short, and $86.40 can be recovered.")
    assert llm.phrase(facts, tmpl).startswith("Heads up")
    monkeypatch.setattr(llm, "complete", lambda p, s=None: None)
    assert llm.phrase(facts, tmpl) == tmpl
    def boom(p, s=None):
        raise RuntimeError("timeout")
    monkeypatch.setattr(llm, "complete", boom)
    assert llm.phrase(facts, tmpl) == tmpl


def test_ask_llm_none_without_key(clean_env):
    assert llm.ask_llm("sales yesterday") is None


def test_square_order_mapping():
    raw = [{"id": "SQ1", "reference_id": "o1", "created_at": "2026-11-06T00:15:00Z", "state": "COMPLETED",
            "source": {"name": "DoorDash"}, "total_tax_money": {"amount": 0}, "total_tip_money": {"amount": 0},
            "line_items": [{"name": "Tonkotsu", "quantity": "2", "base_price_money": {"amount": 1925}}],
            "tenders": [{"type": "CARD"}]},
           {"id": "SQ2", "created_at": "2026-11-05T17:00:00Z", "state": "COMPLETED", "source": {"name": "Square Point of Sale"},
            "line_items": [{"name": "Gyoza", "quantity": "1", "base_price_money": {"amount": 800}}], "tenders": [{"type": "CASH"}]}]
    o, l = square.map_orders(raw, "2026-11-05")
    assert list(o.channel) == ["doordash", "in_store"] and list(o.tender) == ["card", "cash"]
    assert o.subtotal.iloc[0] == 38.50 and len(l) == 3
    assert str(o.created_at.iloc[0]) == "2026-11-05 19:15:00"  # local time


def test_square_shift_mapping_and_window():
    d = [{"id": "S1", "state": "CLOSED", "expected_cash_money": {"amount": 111503}, "closed_cash_money": {"amount": 109153},
          "opened_cash_money": {"amount": 20000}}]
    s = square.map_shifts(d, "2026-11-05")
    assert s.expected_cash[0] == 1115.03 and s.closed_cash[0] == 1091.53
    a, b = square.SquareClient.day_window("2026-11-05")
    assert a == "2026-11-05T09:00:00Z" and b == "2026-11-06T09:00:00Z"


def test_square_sold_out_is_blocked(clean_env, requests_mock):
    clean_env.setenv("SQUARE_ACCESS_TOKEN", "EAAA"); clean_env.setenv("SQUARE_LOCATION_ID", "L1")
    m = requests_mock.post("https://connect.squareupsandbox.com/v2/inventory/changes/batch-create", json={"counts": []})
    with pytest.raises(square.SquareError, match="disabled"):
        square.SquareClient().set_sold_out("VAR1")
    assert m.call_count == 0



def test_doordash_jwt_structure():
    secret = base64.urlsafe_b64encode(b"s" * 32).decode().rstrip("=")
    tok = doordash.make_jwt("dev1", "key1", secret, now=1_800_000_000)
    hdr = jwt.get_unverified_header(tok)
    assert hdr["alg"] == "HS256" and hdr["dd-ver"] == "DD-JWT-V1"
    claims = jwt.decode(tok, b"s" * 32, algorithms=["HS256"], audience="doordash",
                        options={"verify_exp": False, "verify_iat": False, "verify_nbf": False})
    assert claims["iss"] == "dev1" and claims["kid"] == "key1" and claims["exp"] - claims["iat"] == 300


def test_pause_executor_dry_run_and_idempotent(clean_env, tmp_path):
    ex = doordash.AppPauseExecutor(tmp_path / "a.jsonl")
    r1 = ex.pause("hanabi", "2026-11-06", "chashu", "doordash", at="21:15")
    r2 = ex.pause("hanabi", "2026-11-06", "chashu", "doordash", at="21:15")
    assert r1["status"] == "dry_run" and r2["status"] == "duplicate_ignored"


def test_pause_executor_configured_doordash_still_dry_run(clean_env, tmp_path, requests_mock):
    secret = base64.urlsafe_b64encode(b"k" * 32).decode()
    for k, v in {"DOORDASH_DEVELOPER_ID": "d", "DOORDASH_KEY_ID": "k", "DOORDASH_SIGNING_SECRET": secret,
                 "DOORDASH_STORE_ID": "S9"}.items():
        clean_env.setenv(k, v)
    m = requests_mock.put("https://openapi.doordash.com/marketplace/api/v1/stores/S9/items/status", json={"ok": True})
    r = doordash.AppPauseExecutor(tmp_path / "a.jsonl").pause("hanabi", "2026-11-06", "chashu", "doordash")
    assert r["status"] == "dry_run" and m.call_count == 0
    with pytest.raises(RuntimeError, match="disabled"):
        doordash.DoorDashClient().set_item_status("S9", "chashu", False)
    assert m.call_count == 0
