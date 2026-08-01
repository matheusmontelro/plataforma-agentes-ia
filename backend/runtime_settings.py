"""Provider-neutral branding, public URLs, and local runtime paths."""

from __future__ import annotations

import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _text_env(name: str, default: str) -> str:
    return (os.getenv(name) or default).strip()


def _url_env(name: str, default: str) -> str:
    return _text_env(name, default).rstrip("/")


def _path_env(name: str, default: Path) -> Path:
    configured = Path(os.getenv(name) or default).expanduser()
    if not configured.is_absolute():
        configured = PROJECT_ROOT / configured
    return configured.resolve()


APP_NAME = _text_env("APP_NAME", "SUA_EMPRESA")
PUBLIC_APP_URL = _url_env(
    "PUBLIC_APP_URL",
    os.getenv("FRONTEND_URL") or "http://localhost:3004",
)
PUBLIC_BASE_URL = _url_env(
    "PUBLIC_BASE_URL",
    os.getenv("BACKEND_URL") or "http://localhost:8002",
)

RUNTIME_DATA_DIR = _path_env("APP_DATA_DIR", PROJECT_ROOT / "var")
MEDIA_BASE_PATH = _path_env("MEDIA_BASE_PATH", RUNTIME_DATA_DIR / "media")
CHAT_MEMORY_DIR = _path_env("CHAT_MEMORY_DIR", RUNTIME_DATA_DIR / "chatmemory")
LOG_DIR = _path_env("LOG_DIR", RUNTIME_DATA_DIR / "logs")
AD_CAMPAIGN_DIR = _path_env(
    "AD_CAMPAIGN_DIR",
    RUNTIME_DATA_DIR / "ad-campaign",
)
PATTERNS_DIR = _path_env("PATTERNS_DIR", RUNTIME_DATA_DIR / "patterns")
ADAPTIVE_PATTERNS_DIR = _path_env(
    "ADAPTIVE_PATTERNS_DIR",
    RUNTIME_DATA_DIR / "adaptive-patterns",
)
AUTO_LEARNING_DIR = _path_env(
    "AUTO_LEARNING_DIR",
    RUNTIME_DATA_DIR / "auto-learning",
)
AUTO_LEARNING_V2_DIR = _path_env(
    "AUTO_LEARNING_V2_DIR",
    RUNTIME_DATA_DIR / "auto-learning-v2",
)
FALLBACK_MESSAGES_DIR = _path_env(
    "FALLBACK_MESSAGES_DIR",
    RUNTIME_DATA_DIR / "fallback-messages",
)
INVALID_MESSAGES_DIR = _path_env(
    "INVALID_MESSAGES_DIR",
    RUNTIME_DATA_DIR / "invalid-messages",
)
CONVERSATIONS_DB_PATH = _path_env(
    "CONVERSATIONS_DB_PATH",
    RUNTIME_DATA_DIR / "conversations.db",
)
COMPANY_LOGO_DIR = _path_env("COMPANY_LOGO_DIR", RUNTIME_DATA_DIR / "logos")
ACCOUNT_PROFILE_PHOTO_DIR = _path_env(
    "ACCOUNT_PROFILE_PHOTO_DIR",
    RUNTIME_DATA_DIR / "account-profiles",
)
GOOGLE_VISION_CREDENTIALS = _path_env(
    "GOOGLE_VISION_CREDENTIALS",
    RUNTIME_DATA_DIR / "google-vision.json",
)
GOOGLE_CALENDAR_CREDENTIALS = _path_env(
    "GOOGLE_CALENDAR_CREDENTIALS_PATH",
    RUNTIME_DATA_DIR / "google_calendar.json",
)


def app_slug() -> str:
    """Return a provider-safe slug derived from the configured public name."""
    return re.sub(r"[^a-zA-Z0-9._-]+", "-", APP_NAME).strip("-").lower() or "app"


def app_user_agent(component: str = "backend") -> str:
    """Build a conservative HTTP User-Agent without exposing tenant data."""
    slug = app_slug()
    component_slug = re.sub(r"[^a-zA-Z0-9._-]+", "-", component).strip("-")
    return f"{slug}-{component_slug}/1.0" if component_slug else f"{slug}/1.0"
