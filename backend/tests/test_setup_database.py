from pathlib import Path

import pytest
from sqlalchemy import make_url

from scripts.setup_database import (
    OLD_DATABASE_KEYS,
    SetupError,
    database_url,
    parse_args,
    update_env_text,
)

URL_LINE = {"DATABASE_URL": "postgresql://eoe_app:fresh-secret@localhost:5432/eyeofender"}


def test_database_url_replaces_the_old_lines_in_place() -> None:
    before = (
        "SECRET_KEY=keep-me\n"
        "# ── PostgreSQL ──\n"
        "POSTGRES_HOST=localhost\n"
        "POSTGRES_PORT=5432\n"
        "POSTGRES_DB=eyeofender\n"
        "POSTGRES_USER=Servers\n"
        "POSTGRES_PASSWORD=Password\n"
        "# POSTGRES_USER=commented-out lines stay as they are\n"
        "OPENROUTER_API_KEY_1=\n"
    )
    after = update_env_text(before, URL_LINE, OLD_DATABASE_KEYS)
    assert after == (
        "SECRET_KEY=keep-me\n"
        "# ── PostgreSQL ──\n"
        "DATABASE_URL=postgresql://eoe_app:fresh-secret@localhost:5432/eyeofender\n"
        "# POSTGRES_USER=commented-out lines stay as they are\n"
        "OPENROUTER_API_KEY_1=\n"
    )


def test_an_existing_database_url_is_updated_and_windows_line_endings_kept() -> None:
    before = "SECRET_KEY=x\r\nDATABASE_URL=postgresql://postgres:old@localhost/eyeofender\r\n"
    after = update_env_text(before, URL_LINE, OLD_DATABASE_KEYS)
    assert after == f"SECRET_KEY=x\r\nDATABASE_URL={URL_LINE['DATABASE_URL']}\r\n"


def test_a_missing_key_is_added_at_the_end() -> None:
    assert update_env_text("SECRET_KEY=x\n", URL_LINE) == (
        f"SECRET_KEY=x\n\nDATABASE_URL={URL_LINE['DATABASE_URL']}\n"
    )


def test_a_duplicated_key_is_updated_everywhere() -> None:
    # dotenv uses the last occurrence, so leaving one stale copy would undo the fix.
    after = update_env_text("DATABASE_URL=a\nDATABASE_URL=b\n", {"DATABASE_URL": "c"})
    assert after == "DATABASE_URL=c\nDATABASE_URL=c\n"


def _env(tmp_path: Path, text: str) -> list[str]:
    env_file = tmp_path / ".env"
    env_file.write_text(text, encoding="utf-8")
    return ["--env-file", str(env_file)]


def test_defaults_come_from_database_url(tmp_path: Path) -> None:
    args = parse_args(
        _env(tmp_path, "DATABASE_URL=postgresql://postgres:Password@db.local:6543/eyeofender\n")
    )
    assert (args.host, args.port, args.database) == ("db.local", 6543, "eyeofender")
    # The URL already logs in as the superuser, so its password is reused.
    assert args.known_superuser_password == "Password"


def test_superuser_password_is_only_reused_from_a_superuser_url(tmp_path: Path) -> None:
    args = parse_args(
        _env(tmp_path, "DATABASE_URL=postgresql://eoe_app:app-pw@localhost/eyeofender\n")
    )
    assert args.known_superuser_password is None


def test_defaults_also_come_from_the_old_separate_settings(tmp_path: Path) -> None:
    args = parse_args(
        _env(tmp_path, "POSTGRES_HOST=db.local\nPOSTGRES_PORT=6543\nPOSTGRES_DB=eyeofender\n")
    )
    assert (args.host, args.port, args.database, args.app_user) == (
        "db.local",
        6543,
        "eyeofender",
        "eoe_app",
    )


def test_the_written_url_encodes_special_characters(tmp_path: Path) -> None:
    args = parse_args(_env(tmp_path, ""))
    url = database_url(args, "p@ss:w/rd#")
    assert url.startswith("postgresql://eoe_app:")
    assert "p@ss" not in url  # encoded, so the URL stays valid
    assert make_url(url).password == "p@ss:w/rd#"


def test_unsafe_names_are_refused(tmp_path: Path) -> None:
    with pytest.raises(SetupError, match="not a simple name"):
        parse_args([*_env(tmp_path, ""), "--database", 'x"; DROP DATABASE y; --'])
