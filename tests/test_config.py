import pytest

from deja.config import ConfigurationError, Settings, configure_root_certificate


def test_configure_root_certificate_adds_lambda_certificate_path() -> None:
    source = "postgresql://user:secret@example.com:26257/defaultdb?sslmode=verify-full"

    configured = configure_root_certificate(source, "/var/task/certs/root.crt")

    assert "sslmode=verify-full" in configured
    assert "sslrootcert=%2Fvar%2Ftask%2Fcerts%2Froot.crt" in configured


def test_configure_root_certificate_replaces_existing_path() -> None:
    source = (
        "postgresql://user:secret@example.com:26257/defaultdb"
        "?sslmode=verify-full&sslrootcert=%2Fhome%2Fuser%2Froot.crt"
    )

    configured = configure_root_certificate(source, "/var/task/certs/root.crt")

    assert "/home/user" not in configured
    assert configured.count("sslrootcert=") == 1


def test_settings_require_external_service_configuration(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("GROQ_API_KEY", raising=False)

    with pytest.raises(ConfigurationError, match="DATABASE_URL, GROQ_API_KEY"):
        Settings.from_env()


def test_settings_apply_lambda_certificate_without_exposing_secrets(monkeypatch) -> None:
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql://user:secret@example.com:26257/defaultdb?sslmode=verify-full",
    )
    monkeypatch.setenv("GROQ_API_KEY", "test-key")
    monkeypatch.setenv("DATABASE_CA_CERT", "/var/task/certs/root.crt")

    settings = Settings.from_env()

    assert "sslrootcert=%2Fvar%2Ftask%2Fcerts%2Froot.crt" in settings.database_url
    assert "secret" not in repr(settings)
    assert "test-key" not in repr(settings)
