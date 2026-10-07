import pytest
from database_layer.config import DatabaseSettings
from database_layer.errors import ConfigurationError
from sqlalchemy import make_url


def test_db_environment_password_round_trips_and_stays_sanitized(monkeypatch) -> None:
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.setenv("DB_USER", "synthetic_user")
    password = "synthetic/password@value"
    monkeypatch.setenv("DB_PASSWORD", password)
    monkeypatch.setenv("DB_NAME", "synthetic_database")

    settings = DatabaseSettings.from_env()
    parsed = make_url(settings.url)

    if parsed.password != password:
        pytest.fail("DB_PASSWORD did not round-trip through the configured URL")
    if password in settings.sanitized_url:
        pytest.fail("sanitized_url exposed the configured password")
    assert "***" in settings.sanitized_url
    if settings.url in repr(settings):
        pytest.fail("DatabaseSettings repr exposed the raw database URL")
    if password in repr(settings):
        pytest.fail("DatabaseSettings repr exposed the configured password")


def test_database_url_takes_precedence_over_db_environment(monkeypatch) -> None:
    configured_url = "mysql+asyncmy://url_user@db.example/synthetic_database"
    monkeypatch.setenv("DATABASE_URL", configured_url)
    monkeypatch.setenv("DB_USER", "ignored_user")
    monkeypatch.setenv("DB_PASSWORD", "ignored_password")
    monkeypatch.setenv("DB_NAME", "ignored_database")

    settings = DatabaseSettings.from_env()

    if settings.url != configured_url:
        pytest.fail("DATABASE_URL precedence changed")


def test_database_url_rejects_sqlite(monkeypatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "sqlite:///not-an-acceptance-database.db")

    with pytest.raises(ConfigurationError, match="SQLite is not an acceptance database"):
        DatabaseSettings.from_env()
