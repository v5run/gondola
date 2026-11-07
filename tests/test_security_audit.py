"""Offline regression tests for demo security boundaries (not a penetration test)."""
import pytest
from fastapi.testclient import TestClient
from gondola.api.app import app
from gondola.integrations import square, twilio_sms
from gondola.config import Settings


def test_square_blocks_all_writes_even_production_and_seed(requests_mock):
    s = Settings(square_env="production", square_access_token="test", square_location_id="test")
    client = square.SquareClient(s)
    for method, path in [("POST", "/v2/payments"), ("PUT", "/v2/catalog/object"),
                         ("DELETE", "/v2/catalog/object/x")]:
        with pytest.raises(square.SquareError, match="disabled"):
            client._req(method, path)
    with pytest.raises(square.SquareError, match="disabled"):
        client.seed_demo_orders()
    assert requests_mock.call_count == 0


def test_injected_square_client_never_called(tmp_path):
    from gondola.integrations.doordash import AppPauseExecutor
    class Square:
        def set_sold_out(self, *args, **kwargs):
            raise AssertionError("must not call")
    ex = AppPauseExecutor(tmp_path / "actions", square=Square(), square_all_channels=True,
                          square_variation_ids={"item": "variation"})
    assert ex.pause("store", "2026-11-07", "item", "square")["status"] == "dry_run"


def test_twilio_webhook_requires_signature_and_authorized_sender(monkeypatch, tmp_path):
    from gondola import pipeline
    monkeypatch.setattr(pipeline, "OUT", tmp_path)
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "test-token")
    monkeypatch.setenv("ALERT_SMS_TO", "+15555550101")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    c = TestClient(app)
    params = {"From": "+15555550101", "Body": "HELP"}
    url = "https://example.test/api/sms/inbound"
    signature = twilio_sms.expected_signature("test-token", url, params)
    assert c.post("/api/sms/inbound", data=params).status_code == 403
    assert c.post("/api/sms/inbound", data={**params, "Body": "STOP"}, headers={"X-Twilio-Signature": signature}).status_code == 403
    other = {**params, "From": "+15555550102"}
    other_sig = twilio_sms.expected_signature("test-token", url, other)
    assert c.post("/api/sms/inbound", data=other, headers={"X-Twilio-Signature": other_sig}).status_code == 403
    assert c.post("/api/sms/inbound", data=params, headers={"X-Twilio-Signature": signature}).status_code == 200
    monkeypatch.setenv("PUBLIC_BASE_URL", "http://example.test")
    assert c.post("/api/sms/inbound", data=params, headers={"X-Twilio-Signature": signature}).status_code == 403


def test_cors_no_wildcard():
    c = TestClient(app)
    r = c.options("/api/health", headers={"Origin": "https://evil.example", "Access-Control-Request-Method": "GET"})
    assert r.status_code == 400
    assert "access-control-allow-origin" not in r.headers


def test_spa_rejects_symlink_escape(monkeypatch, tmp_path):
    import importlib
    api_app = importlib.import_module("gondola.api.app")
    web = tmp_path / "web"
    web.mkdir()
    (web / "index.html").write_text("home")
    secret = tmp_path / "private.txt"
    secret.write_text("private")
    try:
        (web / "escape.txt").symlink_to(secret)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("Windows account lacks symlink privilege; run this check on symlink-capable CI")
        raise
    monkeypatch.setattr(api_app, "WEB", web)
    c = TestClient(app)
    assert c.get("/escape.txt").status_code == 404
    assert c.get("/some-route").text == "home"


def test_spa_checks_resolved_index_for_every_fallback(monkeypatch, tmp_path):
    """Model index resolution explicitly; complements the real-symlink platform test."""
    import importlib
    from pathlib import Path
    api_app = importlib.import_module("gondola.api.app")
    web = tmp_path / "web"
    web.mkdir()
    index = web / "index.html"
    index.write_text("home", encoding="utf-8")
    outside = tmp_path / "outside.txt"
    outside.write_text("benign outside marker", encoding="utf-8")
    original_resolve = Path.resolve
    def resolve(path, *args, **kwargs):
        return outside if path == index else original_resolve(path, *args, **kwargs)
    monkeypatch.setattr(api_app, "WEB", web)
    monkeypatch.setattr(Path, "resolve", resolve)
    c = TestClient(app)
    for route in ("/index.html", "/", "/present/orders"):
        response = c.get(route)
        assert response.status_code == 404
        assert "benign outside marker" not in response.text


def test_closed_day_does_not_hide_other_step_failures(monkeypatch, tmp_path):
    from gondola import pipeline
    from gondola.tools.sentinel import Notifier
    monkeypatch.setattr(pipeline, "OUT", tmp_path)
    result = pipeline.run_close("2025-12-25", render=False, fail={"report"},
                                notifier=Notifier(tmp_path / "outbox.jsonl"))
    assert result["status"] == "partial"
    assert next(x for x in result["log"] if x["step"] == "report")["status"] == "failed"
    assert all(x["status"] == "skipped" for x in result["log"]
               if x["step"] in {"books", "stock", "analyst"})


def test_notifier_does_not_send_email_with_credentials(monkeypatch, tmp_path, requests_mock):
    from datetime import datetime
    from gondola.tools.sentinel import Notifier
    monkeypatch.setenv("SENDGRID_API_KEY", "test-key")
    monkeypatch.setenv("ALERT_EMAIL_FROM", "sender@example.test")
    monkeypatch.setenv("ALERT_EMAIL_TO", "recipient@example.test")
    requests_mock.post("https://api.sendgrid.com/v3/mail/send", status_code=202)
    rec = Notifier(tmp_path / "outbox").send_email("key", "subject", "body", None, datetime(2026, 11, 7, 12))
    assert rec["status"] == "dry_run"
    assert requests_mock.call_count == 0


def test_host_and_browser_origin_boundaries(monkeypatch, tmp_path):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    from gondola import pipeline
    monkeypatch.setattr(pipeline, "OUT", tmp_path)
    c = TestClient(app, base_url="http://localhost:8000")
    assert c.get("/api/health", headers={"host": "attacker.example"}).status_code == 400
    assert c.get("/api/health", headers={"host": "localhost.attacker.example"}).status_code == 400
    assert c.get("/api/health", headers={"host": "localhost@attacker.example"}).status_code == 400
    assert c.get("/api/health", headers={"host": "localhost:evil"}).status_code == 400
    assert c.get("/api/health", headers={"sec-fetch-site": "cross-site"}).status_code == 403
    assert c.post("/api/sms/inbound", data={"Body": "HELP"}, headers={"origin": "https://attacker.example"}).status_code == 403
    assert c.post("/api/sms/inbound", data={"Body": "HELP"}, headers={"origin": "null"}).status_code == 403
    # Origin-less requests can be local CLI clients; this is not authentication.
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/sms/inbound", data={"Body": "HELP"}, headers={"origin": "http://localhost:8000"}).status_code == 200
    assert c.get("/api/health").headers["cache-control"] == "no-store"


def test_host_boundary_ipv6_and_development_origin(monkeypatch, tmp_path):
    monkeypatch.setenv("TWILIO_AUTH_TOKEN", "")
    from gondola import pipeline
    monkeypatch.setattr(pipeline, "OUT", tmp_path)
    c = TestClient(app, base_url="http://[::1]:8000")
    assert c.get("/api/health").status_code == 200
    assert c.post("/api/sms/inbound", data={"Body": "HELP"}, headers={"origin": "http://[::1]:8000"}).status_code == 200
    c = TestClient(app, base_url="http://localhost:8000")
    assert c.post("/api/sms/inbound", data={"Body": "HELP"}, headers={"origin": "http://localhost:5173"}).status_code == 200


def test_provider_errors_do_not_include_response_body(requests_mock):
    from gondola.integrations import twilio_sms, sendgrid_email
    leak = "secret-provider-response"
    requests_mock.post("https://api.twilio.com/2010-04-01/Accounts/AC1/Messages.json", status_code=400, text=leak)
    with pytest.raises(twilio_sms.TwilioError) as sms_error:
        twilio_sms.send_sms("AC1", "token", "+1", "+2", "body")
    assert leak not in str(sms_error.value)
    requests_mock.post(sendgrid_email.API, status_code=400, text=leak)
    with pytest.raises(sendgrid_email.SendGridError) as email_error:
        sendgrid_email.send_email("key", "from@example.test", ["to@example.test"], "subject", "body")
    assert leak not in str(email_error.value)


def test_report_launch_requires_sandbox(monkeypatch):
    import asyncio
    from types import SimpleNamespace
    from gondola.report import render
    calls = []
    class BrowserType:
        async def launch(self, **kwargs):
            calls.append(kwargs)
            return "browser"
    monkeypatch.setattr(render, "chrome_path", lambda: "/fake/chromium")
    assert asyncio.run(render._launch(SimpleNamespace(chromium=BrowserType()))) == "browser"
    assert calls == [{"executable_path": "/fake/chromium", "chromium_sandbox": True}]


def test_agent_failure_does_not_expose_provider_exception(monkeypatch, tmp_path):
    from gondola.api import rush
    from gondola.rush import store
    from fastapi import FastAPI
    monkeypatch.setattr(store, "DB", tmp_path / "jobs.sqlite")
    async def fail(req, progress):
        raise RuntimeError("sensitive-provider-response")
    monkeypatch.setattr(rush.agents, "controller", fail)
    app = FastAPI()
    app.include_router(rush.router)
    with TestClient(app) as c:
        job = c.post("/api/rush/agent", json={}).json()["id"]
        for _ in range(100):
            result = c.get(f"/api/rush/jobs/{job}").json()
            if result["status"] != "running":
                break
        assert result["status"] == "failed"
        assert "sensitive-provider-response" not in str(result)


def test_demo_entrypoint_refuses_network_binding(monkeypatch):
    from gondola.api import __main__
    called = []
    monkeypatch.setattr(__main__.uvicorn, "run", lambda *args, **kwargs: called.append(kwargs))
    monkeypatch.setenv("GONDOLA_HOST", "0.0.0.0")
    with pytest.raises(SystemExit, match="loopback"):
        __main__.main()
    assert called == []
    monkeypatch.setenv("GONDOLA_HOST", "127.0.0.1")
    __main__.main()
    assert called[0]["host"] == "127.0.0.1"


def test_close_step_failure_does_not_persist_exception_text():
    from gondola import pipeline
    log = []
    def fail():
        raise RuntimeError("sensitive-error-content")
    assert pipeline._timed("example", fail, log, set()) is None
    assert log[0]["status"] == "failed"
    assert "sensitive-error-content" not in str(log)
    assert "trace" not in log[0]
