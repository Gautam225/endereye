"""The building blocks that keep database passwords safe: encryption, log redaction, host checks,
and error messages that never carry driver text. No database needed."""

import asyncio
import ipaddress
import logging
import socket
import ssl

import asyncpg
import pytest

from app.core.config import Settings
from app.core.logging import RedactFilter, redact
from app.core.vault import (
    Vault,
    VaultError,
    VaultNotConfiguredError,
    check_key,
    generate_key,
)
from app.engine.postgres_connect import safe_error, ssl_context
from app.services.network_guard import (
    Target,
    TargetNotAllowedError,
    check_target,
    judge,
    valid_host_syntax,
)

PASSWORD = "s3cret-Pa$$word!"


# ── Vault ────────────────────────────────────────────────────────────────────


def test_a_secret_round_trips_and_is_not_readable_in_storage() -> None:
    vault = Vault.from_keys(generate_key())

    stored = vault.encrypt(PASSWORD, "db_connection:1")

    assert stored.startswith("v1.") and PASSWORD not in stored
    assert vault.decrypt(stored, "db_connection:1") == PASSWORD


def test_every_encryption_is_different_even_for_the_same_secret() -> None:
    vault = Vault.from_keys(generate_key())

    assert vault.encrypt(PASSWORD, "x") != vault.encrypt(PASSWORD, "x")


def test_a_value_copied_to_another_row_does_not_decrypt() -> None:
    vault = Vault.from_keys(generate_key())
    stored = vault.encrypt(PASSWORD, "db_connection:one")

    with pytest.raises(VaultError) as error:
        vault.decrypt(stored, "db_connection:two")

    assert PASSWORD not in error.value.message


def test_a_tampered_or_foreign_value_is_refused_without_details() -> None:
    vault = Vault.from_keys(generate_key())
    stored = vault.encrypt(PASSWORD, "x")
    flipped = stored[:-3] + ("AAA" if not stored.endswith("AAA") else "BBB")

    for bad in (flipped, "garbage", "v1.deadbeef.AAAA", "v2." + stored.split(".", 1)[1]):
        with pytest.raises(VaultError):
            vault.decrypt(bad, "x")
    other = Vault.from_keys(generate_key())
    with pytest.raises(VaultError):
        other.decrypt(stored, "x")


def test_after_a_key_change_old_values_still_read_until_they_are_saved_again() -> None:
    old_key, new_key = generate_key(), generate_key()
    stored = Vault.from_keys(old_key).encrypt(PASSWORD, "x")

    rotated = Vault.from_keys(new_key, previous=old_key)

    assert rotated.decrypt(stored, "x") == PASSWORD
    assert rotated.needs_rotation(stored)
    fresh = rotated.encrypt(PASSWORD, "x")
    assert not rotated.needs_rotation(fresh)
    with pytest.raises(VaultError):
        Vault.from_keys(new_key).decrypt(stored, "x")  # without the previous key it cannot


def test_a_missing_or_bad_key_is_explained_and_never_echoed() -> None:
    with pytest.raises(VaultNotConfiguredError, match="CONNECTION_ENCRYPTION_KEY"):
        Vault.from_keys(None)
    with pytest.raises(VaultNotConfiguredError) as error:
        Vault.from_keys("not-a-key-sk-1234")
    assert "sk-1234" not in error.value.message
    with pytest.raises(ValueError, match="32 bytes"):
        check_key("AAAA")


def test_generated_keys_are_valid_and_unique() -> None:
    assert generate_key() != generate_key()
    check_key(generate_key())


# ── Log redaction ────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "line",
    [
        f"connect postgresql://reader:{PASSWORD}@db.example.com:5432/sales failed",
        f"password={PASSWORD} host=db",
        f"password: {PASSWORD}",
        f'{{"password": "{PASSWORD}"}}',
        f"token = '{PASSWORD}'",
    ],
)
def test_passwords_are_hidden_in_log_lines(line: str) -> None:
    assert PASSWORD not in redact(line)
    assert "***" in redact(line)


def test_log_lines_without_secrets_are_unchanged() -> None:
    line = "Connection tested: status ok on host db.example.com"

    assert redact(line) == line


def test_the_log_filter_cleans_messages_and_secret_named_fields() -> None:
    record = logging.LogRecord("t", logging.INFO, "", 0, "using password=%s", (PASSWORD,), None)
    record.api_key = PASSWORD
    record.note = f"password={PASSWORD}"

    RedactFilter().filter(record)

    assert PASSWORD not in record.getMessage()
    assert record.api_key == "***" and PASSWORD not in record.note


# ── Where a connection may point ─────────────────────────────────────────────


@pytest.fixture
def strict(settings: Settings) -> Settings:
    return settings.model_copy(
        update={
            "external_db_allow_loopback": False,
            "external_db_allow_private": True,
            "external_db_allowed_hosts": [],
        }
    )


@pytest.mark.parametrize(
    ("address", "allowed"),
    [
        ("8.8.8.8", True),
        ("10.1.2.3", True),
        ("192.168.0.5", True),
        ("127.0.0.1", False),
        ("::1", False),
        ("::ffff:127.0.0.1", False),  # loopback hidden inside an IPv6 address
        ("169.254.169.254", False),  # cloud metadata
        ("fd00:ec2::254", False),
        ("169.254.10.10", False),
        ("0.0.0.0", False),
        ("224.0.0.1", False),
        ("240.0.0.1", False),
    ],
)
def test_which_addresses_may_be_used(strict: Settings, address: str, allowed: bool) -> None:
    result = judge(ipaddress.ip_address(address), strict)

    assert (result is None) is allowed


def test_loopback_and_private_addresses_follow_their_settings(strict: Settings) -> None:
    dev = strict.model_copy(update={"external_db_allow_loopback": True})
    closed = strict.model_copy(update={"external_db_allow_private": False})

    assert judge(ipaddress.ip_address("127.0.0.1"), dev) is None
    assert judge(ipaddress.ip_address("10.0.0.1"), closed) is not None
    assert judge(ipaddress.ip_address("169.254.169.254"), dev) is not None  # never allowed


@pytest.mark.parametrize(
    "host",
    ["db.example.com", "10.0.0.5", "localhost", "db-1", "::1", "2001:db8::1"],
)
def test_plain_hosts_pass_the_syntax_check(host: str) -> None:
    assert valid_host_syntax(host)


@pytest.mark.parametrize(
    "host",
    [
        "http://db.example.com",
        "user@db.example.com",
        "db.example.com/path",
        "db.example.com:5432",
        "db example.com",
        "db.example.com?x=1",
        "",
        "-bad.example.com",
        "a" * 300,
    ],
)
def test_anything_that_is_not_a_plain_host_is_refused(host: str) -> None:
    assert not valid_host_syntax(host)


def test_a_host_outside_the_allow_list_is_refused(strict: Settings) -> None:
    listed = strict.model_copy(update={"external_db_allowed_hosts": ["db.example.com"]})

    with pytest.raises(TargetNotAllowedError, match="allowed hosts"):
        asyncio.run(check_target(Target("other.example.com", 5432, "sales"), listed))


def test_the_cloud_metadata_name_and_address_are_refused(strict: Settings) -> None:
    for host in ("metadata.google.internal", "169.254.169.254"):
        with pytest.raises(TargetNotAllowedError):
            asyncio.run(check_target(Target(host, 80, "x"), strict))


def test_an_unencrypted_connection_to_a_public_address_is_refused(strict: Settings) -> None:
    with pytest.raises(TargetNotAllowedError, match="unencrypted"):
        asyncio.run(check_target(Target("8.8.8.8", 5432, "x"), strict, "disable"))


def test_the_apps_own_database_is_refused_even_when_loopback_is_allowed(
    settings: Settings,
) -> None:
    own = settings.sqlalchemy_url
    dev = settings.model_copy(update={"external_db_allow_loopback": True})

    for host in ("localhost", "127.0.0.1", own.host or "localhost"):
        with pytest.raises(TargetNotAllowedError, match="own database"):
            asyncio.run(check_target(Target(host, own.port or 5432, own.database or ""), dev))
    # another database on the same server is a different thing
    asyncio.run(check_target(Target("localhost", own.port or 5432, "another_database"), dev))


# ── Errors that carry no driver text ─────────────────────────────────────────


@pytest.mark.parametrize(
    ("error", "category"),
    [
        (TimeoutError(), "timeout"),
        (ssl.SSLError("secret host detail"), "tls"),
        (
            ConnectionError('PostgreSQL server at "db.internal.corp:5432" rejected SSL upgrade'),
            "tls",
        ),
        (socket.gaierror("db.internal.corp"), "dns"),
        (ConnectionRefusedError("10.0.0.5:5432"), "refused"),
        (asyncpg.InvalidPasswordError("password authentication failed for user bob"), "auth"),
        (asyncpg.InvalidCatalogNameError('database "payroll" does not exist'), "database"),
        (asyncpg.UndefinedTableError('relation "salaries" does not exist'), "database_error"),
        (OSError("No route to host 10.0.0.5"), "network"),
        (RuntimeError("anything"), "unknown"),
    ],
)
def test_connection_errors_become_fixed_messages_without_driver_text(
    error: BaseException, category: str
) -> None:
    found, message = safe_error(error, 5)

    assert found == category
    for leaked in ("10.0.0.5", "bob", "payroll", "salaries", "internal.corp", "secret host"):
        assert leaked not in message


def test_ssl_modes_check_what_they_say() -> None:
    assert ssl_context("disable") is False
    full, ca, require = ssl_context("verify-full"), ssl_context("verify-ca"), ssl_context("require")
    assert full.check_hostname and full.verify_mode == ssl.CERT_REQUIRED
    assert not ca.check_hostname and ca.verify_mode == ssl.CERT_REQUIRED
    assert not require.check_hostname and require.verify_mode == ssl.CERT_NONE
