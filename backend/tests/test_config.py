from pathlib import Path

import pytest

from app.core.config import ConfigError, load_settings

SECRET = "test-secret-" + "x" * 32
DATABASE_ENV = [
    "DATABASE_URL",
    *(f"POSTGRES_{p}" for p in ("HOST", "PORT", "DB", "USER", "PASSWORD")),
]


@pytest.fixture(autouse=True)
def no_database_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Start each test without the test DATABASE_URL that conftest puts in the environment."""
    for name in DATABASE_ENV:
        monkeypatch.delenv(name, raising=False)


def test_missing_database_settings_give_a_clear_error() -> None:
    with pytest.raises(ConfigError, match=r"DATABASE_URL is missing\. Set it in \.env"):
        load_settings(_env_file=None, secret_key=SECRET)


def test_empty_values_count_as_missing(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "")
    monkeypatch.setenv("POSTGRES_PASSWORD", "")
    with pytest.raises(ConfigError, match="DATABASE_URL is missing"):
        load_settings(_env_file=None, secret_key=SECRET)


def test_database_url_is_read_as_one_line(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://postgres:Password@localhost:5432/eyeofender")
    url = load_settings(_env_file=None, secret_key=SECRET).sqlalchemy_url
    assert (url.drivername, url.username, url.password) == (
        "postgresql+asyncpg",
        "postgres",
        "Password",
    )
    assert (url.host, url.port, url.database) == ("localhost", 5432, "eyeofender")
    assert "Password" not in repr(url)  # the password is masked when printed


def test_database_url_accepts_postgres_scheme_and_encoded_passwords(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgres://app:p%40ss%3Aw%2Frd@db.local/eye")
    url = load_settings(_env_file=None, secret_key=SECRET).sqlalchemy_url
    assert (url.drivername, url.password, url.host) == (
        "postgresql+asyncpg",
        "p@ss:w/rd",
        "db.local",
    )


@pytest.mark.parametrize(
    ("value", "problem"),
    [
        ("mysql://u:secret-pw@localhost/db", "must start with postgresql://"),
        ("postgresql://u:secret-pw@localhost:5432/", "has no database name"),
        ("postgresql://u:secret-pw@localhost:notaport/db", "is not a valid URL"),
        ("just text secret-pw", "is not a valid URL"),
    ],
)
def test_bad_database_urls_are_explained_without_showing_the_password(
    monkeypatch: pytest.MonkeyPatch, value: str, problem: str
) -> None:
    monkeypatch.setenv("DATABASE_URL", value)
    with pytest.raises(ConfigError, match=f"DATABASE_URL: {problem}") as caught:
        load_settings(_env_file=None, secret_key=SECRET)
    assert "secret-pw" not in str(caught.value)


def test_database_url_wins_over_the_separate_settings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DATABASE_URL", "postgresql://from_url:pw@url-host:6543/url_db")
    monkeypatch.setenv("POSTGRES_HOST", "parts-host")
    monkeypatch.setenv("POSTGRES_PASSWORD", "parts-pw")
    url = load_settings(_env_file=None, secret_key=SECRET).sqlalchemy_url
    assert (url.username, url.host, url.port, url.database) == (
        "from_url",
        "url-host",
        6543,
        "url_db",
    )


def test_separate_settings_still_work_and_escape_special_characters() -> None:
    settings = load_settings(_env_file=None, postgres_password="p@ss:w/rd%#", secret_key=SECRET)
    url = settings.sqlalchemy_url
    assert url.password == "p@ss:w/rd%#"
    assert "p@ss:w/rd%#" not in str(url)  # str() masks the password
    assert url.drivername == "postgresql+asyncpg"


def test_cors_origins_from_comma_separated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "http://localhost:5173, https://app.example.com/")
    settings = load_settings(_env_file=None, postgres_password="x", secret_key=SECRET)
    assert settings.cors_origins == ["http://localhost:5173", "https://app.example.com"]


def test_cors_wildcard_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CORS_ORIGINS", "*")
    with pytest.raises(ConfigError, match="CORS_ORIGINS"):
        load_settings(_env_file=None, postgres_password="x", secret_key=SECRET)


def test_numbered_keys_are_collected_in_number_order(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY_2", "second")
    monkeypatch.setenv("OPENROUTER_API_KEY_10", "tenth")
    monkeypatch.setenv("OPENROUTER_API_KEY_1", "first")
    monkeypatch.setenv("OPENROUTER_API_KEY_3", "   ")  # blank slots are skipped

    settings = load_settings(_env_file=None, postgres_password="x", secret_key=SECRET)

    keys = [key.get_secret_value() for key in settings.openrouter_api_keys]
    assert keys == ["first", "second", "tenth"]


def test_numbered_keys_come_from_env_file_and_real_env_wins(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GROQ_API_KEY_1=file-one\nGROQ_API_KEY_2=file-two\nGROQ_API_KEY_4=\n", encoding="utf-8"
    )
    monkeypatch.setenv("GROQ_API_KEY_2", "env-two")

    settings = load_settings(_env_file=env_file, postgres_password="x", secret_key=SECRET)

    assert [key.get_secret_value() for key in settings.groq_api_keys] == ["file-one", "env-two"]


def test_model_lists_are_comma_separated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_MODELS_SMART", "a/one:free, b/two:free")
    settings = load_settings(_env_file=None, postgres_password="x", secret_key=SECRET)
    assert settings.openrouter_models_smart == ["a/one:free", "b/two:free"]


def test_model_id_with_a_space_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_MODELS_FAST", "openai/gpt-oss-20b openai/gpt-oss-120b")
    with pytest.raises(ConfigError, match="GROQ_MODELS_FAST"):
        load_settings(_env_file=None, postgres_password="x", secret_key=SECRET)


def test_short_secret_key_is_rejected() -> None:
    with pytest.raises(ConfigError, match="SECRET_KEY: must be at least 32"):
        load_settings(_env_file=None, postgres_password="x", secret_key="too-short")
