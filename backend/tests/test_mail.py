"""The mail account set up in the app, and each person's saved email addresses (needs the test
database). No real mail is sent: the last step of sending is scripted."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

import time
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import SecretStr
from test_chat import small_space
from test_dashboards import answered, pin
from test_spaces import ADMIN, admin, api, code, data_dir, external, new_space, person  # noqa: F401

from app.core.vault import generate_key
from app.main import create_app
from app.services import mailer

pytestmark = pytest.mark.db

GMAIL = {
    "host": "smtp.gmail.com",
    "port": 587,
    "security": "starttls",
    "username": "me@gmail.com",
    "password": "app-password-1234",
    "from_address": "me@gmail.com",
}


class Wire:
    """Stands in for the SMTP conversation and keeps what it was asked to send."""

    def __init__(self) -> None:
        self.sent: list[tuple[mailer.MailConfig, Any]] = []
        self.fail: str | None = None

    def __call__(self, config: mailer.MailConfig, message: Any) -> None:
        if self.fail:
            raise mailer.MailError(self.fail)
        self.sent.append((config, message))


@pytest.fixture
def wire(monkeypatch: pytest.MonkeyPatch) -> Wire:
    box = Wire()
    monkeypatch.setattr(mailer, "_send", box)
    return box


@pytest.fixture
def client(settings: Any, clean_db: None, data_dir: Any) -> Any:
    """An app with no SMTP in .env and a key for saved passwords."""
    custom = settings.model_copy(
        update={
            "data_dir": data_dir,
            "smtp_host": "",
            "smtp_from": "",
            "smtp_username": "",
            "smtp_password": None,
            "connection_encryption_key": SecretStr(generate_key()),
            "report_scheduler": False,
        }
    )
    with TestClient(create_app(custom)) as test_client:
        yield test_client


def test_only_administrators_can_see_or_change_the_mail_account(client: TestClient) -> None:
    boss = admin(client)
    viewer = person(client, boss, "vi@example.com", "viewer")

    for call in (
        viewer.get("/mail"),
        viewer.put("/mail", json=GMAIL),
        viewer.delete("/mail"),
        viewer.post("/mail/test", json={}),
    ):
        assert call.status_code == 403
    assert boss.get("/mail").json()["source"] == "none"


def test_the_account_is_saved_without_ever_sending_the_password_back(
    client: TestClient, sql: Any
) -> None:
    boss = admin(client)

    saved = boss.put("/mail", json=GMAIL)

    assert saved.status_code == 200, saved.text
    body = saved.json()
    assert (body["configured"], body["source"], body["host"]) == (True, "app", "smtp.gmail.com")
    assert body["has_password"] is True and "password" not in body
    assert "app-password-1234" not in saved.text
    stored = sql("SELECT password_encrypted FROM mail_settings")[0][0]
    assert stored.startswith("v1.") and "app-password-1234" not in stored
    assert boss.get("/mail").json()["updated_by_name"]


def test_an_omitted_password_is_kept_and_an_empty_one_removes_it(client: TestClient) -> None:
    boss = admin(client)
    boss.put("/mail", json=GMAIL)

    kept = boss.put("/mail", json={**GMAIL, "password": None, "port": 465, "security": "ssl"})
    cleared = boss.put("/mail", json={**GMAIL, "password": ""})

    assert kept.json()["has_password"] is True and kept.json()["port"] == 465
    assert cleared.json()["has_password"] is False


def test_a_test_email_is_sent_with_the_saved_account(client: TestClient, wire: Wire) -> None:
    boss = admin(client)
    boss.put("/mail", json=GMAIL)

    sent = boss.post("/mail/test", json={"to": "Friend@Yopmail.com"})

    assert sent.json() == {
        "ok": True,
        "message": "The test email was sent.",
        "sent_to": "friend@yopmail.com",
    }
    ((config, message),) = wire.sent
    assert (config.host, config.username, config.password) == (
        "smtp.gmail.com",
        "me@gmail.com",
        "app-password-1234",
    )  # the password was decrypted for the send, and only for it
    assert config.source == "app" and message["To"] == "friend@yopmail.com"
    assert "app-password" not in repr(config)

    boss.post("/mail/test", json={})
    assert wire.sent[-1][1]["To"] == ADMIN["email"]  # to yourself unless told otherwise


def test_a_failed_test_says_why_instead_of_raising(client: TestClient, wire: Wire) -> None:
    boss = admin(client)
    boss.put("/mail", json=GMAIL)
    wire.fail = "The mail server refused the sign-in."

    result = boss.post("/mail/test", json={})

    assert result.status_code == 200
    assert result.json()["ok"] is False and "refused the sign-in" in result.json()["message"]
    assert boss.post("/mail/test", json={"to": "not-an-email"}).status_code == 422


def test_without_a_test_the_account_is_not_configured_and_clearing_goes_back(
    client: TestClient,
) -> None:
    boss = admin(client)
    space_id = small_space(boss)
    assert boss.get(f"/spaces/{space_id}/reports/options").json()["email_configured"] is False

    boss.put("/mail", json=GMAIL)
    assert boss.get(f"/spaces/{space_id}/reports/options").json()["email_configured"] is True
    cleared = boss.delete("/mail").json()

    assert (cleared["configured"], cleared["source"]) == (False, "none")
    assert boss.get(f"/spaces/{space_id}/reports/options").json()["email_configured"] is False


def test_a_report_is_emailed_from_the_account_set_up_in_the_app(
    client: TestClient, wire: Wire
) -> None:
    boss = admin(client)
    space_id = small_space(boss)
    cid, mid = answered(boss, space_id)
    item = pin(boss, space_id, cid, mid).json()["id"]
    boss.put("/mail", json=GMAIL)
    report = boss.post(
        f"/spaces/{space_id}/reports",
        json={"name": "Weekly", "item_ids": [item], "recipients": ["them@yopmail.com"]},
    ).json()

    boss.post(f"/spaces/{space_id}/reports/{report['id']}/run")
    for _ in range(300):
        runs = boss.get(f"/spaces/{space_id}/reports/{report['id']}/runs").json()
        if runs and runs[0]["status"] != "running":
            break
        time.sleep(0.1)

    assert runs[0]["status"] == "ok" and runs[0]["emailed_to"] == ["them@yopmail.com"]
    ((config, message),) = wire.sent
    assert config.source == "app" and message["To"] == "them@yopmail.com"
    assert next(p.get_filename() for p in message.iter_attachments()).endswith(".pdf")


def test_a_password_cannot_be_stored_without_the_encryption_key(
    settings: Any, clean_db: None, data_dir: Any
) -> None:
    custom = settings.model_copy(
        update={
            "data_dir": data_dir,
            "smtp_host": "",
            "connection_encryption_key": None,
            "report_scheduler": False,
        }
    )
    with TestClient(create_app(custom)) as no_key:
        boss = admin(no_key)

        assert boss.get("/mail").json()["vault_ready"] is False
        refused = boss.put("/mail", json=GMAIL)
        no_password = boss.put("/mail", json={**GMAIL, "password": None, "username": ""})

        assert refused.status_code == 400 and "CONNECTION_ENCRYPTION_KEY" in refused.text
        assert no_password.status_code == 200 and no_password.json()["has_password"] is False


# ── Saved addresses ──────────────────────────────────────────────────────────


def test_a_person_keeps_a_list_of_addresses_that_only_they_can_see(client: TestClient) -> None:
    boss = admin(client)
    other = person(client, boss, "other@example.com", "editor")

    first = boss.post("/me/recipients", json={"email": "Boss@Yopmail.com", "label": "My boss"})
    boss.post("/me/recipients", json={"email": "a@yopmail.com"})
    duplicate = boss.post("/me/recipients", json={"email": "boss@yopmail.com"})
    invalid = boss.post("/me/recipients", json={"email": "nope"})

    assert first.status_code == 201 and first.json()["email"] == "boss@yopmail.com"
    assert (duplicate.status_code, code(duplicate)) == (409, "recipient_exists")
    assert invalid.status_code == 422
    assert [r["email"] for r in boss.get("/me/recipients").json()] == [
        "a@yopmail.com",
        "boss@yopmail.com",
    ]
    assert other.get("/me/recipients").json() == []
    assert other.delete(f"/me/recipients/{first.json()['id']}").status_code == 404
    assert boss.delete(f"/me/recipients/{first.json()['id']}").status_code == 204
    assert len(boss.get("/me/recipients").json()) == 1


def test_everyone_can_see_whether_email_works_but_not_the_settings(client: TestClient) -> None:
    boss = admin(client)
    viewer = person(client, boss, "vi@example.com", "viewer")

    before = viewer.get("/mail/status")
    boss.put("/mail", json=GMAIL)
    after = viewer.get("/mail/status")

    assert before.json() == {"configured": False, "from_address": ""}
    assert after.json() == {"configured": True, "from_address": "me@gmail.com"}
    assert "host" not in after.json() and "smtp" not in after.text
    assert viewer.get("/mail").status_code == 403  # the details are still for administrators
