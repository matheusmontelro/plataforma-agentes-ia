import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("CLIENT_TOKEN", "test-client-token")
os.environ.setdefault("DATABASE_URL", "sqlite:///./test.db")
os.environ.setdefault("WAHA_API_KEY", "test-waha-key")
os.environ.setdefault("WAHA_BASE_URL", "http://waha.local")

from backend.routes.webhook import _is_waha_session_not_found_error


def test_waha_session_not_found_detector_accepts_waha_404_message():
    error = Exception(
        "Erro na requisição: 404 Client Error: Not Found for url: "
        "http://waha.local/api/sessions/sessao-exemplo"
    )

    assert _is_waha_session_not_found_error(error)


def test_waha_session_not_found_detector_accepts_session_not_found_message():
    assert _is_waha_session_not_found_error(Exception("Session not found"))


def test_waha_session_not_found_detector_rejects_other_errors():
    assert not _is_waha_session_not_found_error(Exception("500 Internal Server Error"))
