import importlib.util
from pathlib import Path

import pytest


CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.py"


def _load_config(module_name: str):
    spec = importlib.util.spec_from_file_location(module_name, CONFIG_PATH)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _production_base_env(monkeypatch):
    monkeypatch.setenv("ENVIRONMENT", "production")
    monkeypatch.setenv("DATABASE_URL", "postgresql://public@localhost/app")
    monkeypatch.setenv("PUBLIC_BASE_URL", "https://example.test")
    monkeypatch.delenv("CLIENT_TOKEN", raising=False)
    monkeypatch.delenv("WAHA_API_KEY", raising=False)


def test_optional_whatsapp_integrations_do_not_block_production_boot(monkeypatch):
    _production_base_env(monkeypatch)
    monkeypatch.setenv("WAHA_ENABLED", "false")

    config = _load_config("backend_config_optional_integrations")

    assert config.CLIENT_TOKEN == ""
    assert config.WAHA_ENABLED is False
    assert config.WAHA_API_KEY == ""


def test_enabled_waha_still_requires_api_key_in_production(monkeypatch):
    _production_base_env(monkeypatch)
    monkeypatch.setenv("WAHA_ENABLED", "true")

    with pytest.raises(RuntimeError, match="WAHA_API_KEY"):
        _load_config("backend_config_missing_waha_key")
