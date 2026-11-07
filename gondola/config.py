"""Settings for the optional live integrations.

Everything here is optional: with no .env, Gondola runs fully offline (texts and emails go to out/outbox.jsonl,
POS and app actions go to out/actions_log.jsonl, wording comes from templates).
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _load_dotenv() -> None:
    try:
        from dotenv import load_dotenv
    except ImportError:  # optional dependency
        return
    load_dotenv(ROOT / ".env", override=False)


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _list(name: str) -> list[str]:
    return [x.strip() for x in _env(name).split(",") if x.strip()]


@dataclass
class Settings:
    twilio_account_sid: str = ""
    twilio_auth_token: str = ""
    twilio_from: str = ""
    alert_sms_to: list[str] = field(default_factory=list)
    sendgrid_api_key: str = ""
    alert_email_from: str = ""
    alert_email_to: list[str] = field(default_factory=list)
    google_api_key: str = ""
    gondola_model: str = "gemini-flash-latest"
    anthropic_api_key: str = ""
    gondola_anthropic_model: str = "claude-sonnet-5-5"
    square_access_token: str = ""
    square_location_id: str = ""
    square_env: str = "sandbox"
    doordash_developer_id: str = ""
    doordash_key_id: str = ""
    doordash_signing_secret: str = ""
    doordash_store_id: str = ""
    chrome_path: str = ""
    public_base_url: str = ""

    @property
    def twilio_live(self) -> bool:
        return bool(self.twilio_account_sid and self.twilio_auth_token and self.twilio_from and self.alert_sms_to)

    @property
    def sendgrid_live(self) -> bool:
        return bool(self.sendgrid_api_key and self.alert_email_from and self.alert_email_to)

    @property
    def llm_provider(self) -> str | None:
        if self.google_api_key:
            return "gemini"
        if self.anthropic_api_key:
            return "anthropic"
        return None

    @property
    def square_live(self) -> bool:
        return bool(self.square_access_token and self.square_location_id)

    @property
    def doordash_live(self) -> bool:
        return bool(self.doordash_developer_id and self.doordash_key_id and self.doordash_signing_secret and self.doordash_store_id)


def get_settings() -> Settings:
    """Read settings fresh each call (cheap), so tests and a running server pick up env changes."""
    _load_dotenv()
    return Settings(
        twilio_account_sid=_env("TWILIO_ACCOUNT_SID"),
        twilio_auth_token=_env("TWILIO_AUTH_TOKEN"),
        twilio_from=_env("TWILIO_FROM"),
        alert_sms_to=_list("ALERT_SMS_TO"),
        sendgrid_api_key=_env("SENDGRID_API_KEY"),
        alert_email_from=_env("ALERT_EMAIL_FROM"),
        alert_email_to=_list("ALERT_EMAIL_TO"),
        google_api_key=_env("GOOGLE_API_KEY"),
        gondola_model=_env("GONDOLA_MODEL", "gemini-flash-latest"),
        anthropic_api_key=_env("ANTHROPIC_API_KEY"),
        gondola_anthropic_model=_env("GONDOLA_ANTHROPIC_MODEL", "claude-sonnet-5-5"),
        square_access_token=_env("SQUARE_ACCESS_TOKEN"),
        square_location_id=_env("SQUARE_LOCATION_ID"),
        square_env=_env("SQUARE_ENV", "sandbox") or "sandbox",
        doordash_developer_id=_env("DOORDASH_DEVELOPER_ID"),
        doordash_key_id=_env("DOORDASH_KEY_ID"),
        doordash_signing_secret=_env("DOORDASH_SIGNING_SECRET"),
        doordash_store_id=_env("DOORDASH_STORE_ID"),
        chrome_path=_env("CHROME_PATH"),
        public_base_url=_env("PUBLIC_BASE_URL"),
    )


def integrations_status(s: Settings | None = None) -> dict:
    """Shape of GET /api/integrations."""
    s = s or get_settings()
    model = None
    if s.llm_provider == "gemini":
        model = s.gondola_model
    elif s.llm_provider == "anthropic":
        model = s.gondola_anthropic_model
    return {
        "twilio": {"live": s.twilio_live, "from": s.twilio_from or None},
        "sendgrid": {"live": s.sendgrid_live},
        "llm": {"live": s.llm_provider is not None, "provider": s.llm_provider, "model": model},
        "square": {"live": s.square_live, "env": s.square_env},
        "doordash": {"live": s.doordash_live},
        "agents": agents_status(s),
    }


def agents_status(s: Settings | None = None) -> dict:
    """Agent mode: GONDOLA_AGENTS=adk plus a model key -> the ADK agent graph writes the close wording and answers
    Ask; otherwise the deterministic pipeline and templates (offline)."""
    s = s or get_settings()
    want = _env("GONDOLA_AGENTS").lower() == "adk"
    has_model = bool(s.google_api_key or _env("GOOGLE_GENAI_USE_VERTEXAI").lower() in ("1", "true") or s.anthropic_api_key)
    live = want and has_model
    return {"live": live, "mode": "adk" if live else "offline", "requested": want}
