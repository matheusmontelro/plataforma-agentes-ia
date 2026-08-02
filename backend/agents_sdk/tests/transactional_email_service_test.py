from backend.services import transactional_email_service as service


class FakeSMTP:
    def __init__(self, host, port, timeout):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.ehlo_calls = 0
        self.starttls_context = None
        self.login_args = None
        self.message = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def ehlo(self):
        self.ehlo_calls += 1

    def starttls(self, *, context):
        self.starttls_context = context

    def login(self, username, password):
        self.login_args = (username, password)

    def send_message(self, message):
        self.message = message


def test_password_reset_email_skips_when_smtp_is_not_configured(monkeypatch):
    monkeypatch.delenv("SMTP_HOST", raising=False)
    monkeypatch.delenv("SMTP_FROM_EMAIL", raising=False)

    result = service.send_password_reset_email(
        to_email="owner@example.com",
        to_name="Owner",
        reset_url="https://app.example.com/reset-password?token=test",
        expires_minutes=60,
    )

    assert result.sent is False
    assert result.skipped is True
    assert result.reason == "smtp_not_configured"


def test_password_setup_email_uses_generic_smtp_and_local_template(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_PORT", "2525")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@example.com")
    monkeypatch.setenv("SMTP_FROM_NAME", "Empresa Exemplo")
    monkeypatch.setenv("SMTP_STARTTLS", "true")

    smtp_instances = []

    def smtp_factory(*args, **kwargs):
        smtp = FakeSMTP(*args, **kwargs)
        smtp_instances.append(smtp)
        return smtp

    monkeypatch.setattr(service.smtplib, "SMTP", smtp_factory)

    result = service.send_password_setup_email(
        to_email="client@example.com",
        to_name="Cliente <Exemplo>",
        workspace_name="Clínica\nExemplo",
        setup_url="https://app.example.com/reset-password?token=one-time",
        expires_minutes=90,
    )

    assert result.sent is True
    assert result.skipped is False
    smtp = smtp_instances[0]
    assert (smtp.host, smtp.port, smtp.timeout) == (
        "smtp.example.com",
        2525,
        service.SMTP_TIMEOUT_SECONDS,
    )
    assert smtp.ehlo_calls == 2
    assert smtp.starttls_context is not None
    assert smtp.login_args == ("smtp-user", "smtp-password")
    assert smtp.message["From"] == "Empresa Exemplo <no-reply@example.com>"
    assert smtp.message["To"] == '"Cliente <Exemplo>" <client@example.com>'
    assert smtp.message["Subject"] == "Defina sua senha em Clínica Exemplo"
    assert "smtp-password" not in smtp.message.as_string()
    assert "one-time" in smtp.message.as_string()
    assert "&lt;Exemplo&gt;" in smtp.message.as_string()


def test_smtp_authentication_requires_username_and_password_together(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.delenv("SMTP_PASSWORD", raising=False)

    assert service.get_smtp_config() is None


def test_invalid_smtp_port_falls_back_to_587(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@example.com")
    monkeypatch.setenv("SMTP_PORT", "70000")

    config = service.get_smtp_config()

    assert config is not None
    assert config.port == 587


def test_invalid_starttls_value_falls_back_to_secure_default(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@example.com")
    monkeypatch.setenv("SMTP_STARTTLS", "treu")

    config = service.get_smtp_config()

    assert config is not None
    assert config.starttls is True


def test_smtp_authentication_is_rejected_without_starttls(monkeypatch):
    monkeypatch.setenv("SMTP_HOST", "smtp.example.com")
    monkeypatch.setenv("SMTP_FROM_EMAIL", "no-reply@example.com")
    monkeypatch.setenv("SMTP_USERNAME", "smtp-user")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password")
    monkeypatch.setenv("SMTP_STARTTLS", "false")

    assert service.get_smtp_config() is None


def test_public_app_origin_uses_provider_neutral_setting(monkeypatch):
    monkeypatch.setenv("PUBLIC_APP_URL", "https://app.example.com/")

    assert service.get_public_app_origin() == "https://app.example.com"
