"""Invitations and forgotten passwords: one-time links sent by email (needs the test database).
The mail server is scripted; everything else is real."""

# The fixtures imported from other test files are used by name, which ruff reads as redefinitions.
# ruff: noqa: F811

from collections.abc import Callable
from typing import Any

import pytest
from fastapi.testclient import TestClient
from test_spaces import ADMIN, Person, api, data_dir, external, person  # noqa: F401

from app.services import mail_config, mailer

pytestmark = pytest.mark.db

GOOD = "a-long-new-password"


@pytest.fixture
def admin(api: TestClient) -> Person:
    body = api.post("/api/v1/auth/setup", json=ADMIN).json()
    return Person(api, body["access_token"], body["user"]["id"])


class Outbox:
    def __init__(self) -> None:
        self.sent: list[dict[str, Any]] = []
        self.fail: str | None = None

    async def send(self, settings: Any, to: list[str], subject: str, body: str, files: Any) -> None:
        if self.fail:
            raise mailer.MailError(self.fail)
        self.sent.append({"to": to, "subject": subject, "body": body})

    def link(self, kind: str) -> str:
        """The token in the last email, as a person would copy it from the message."""
        body = self.sent[-1]["body"]
        return next(w for w in body.split() if f"/{kind}/" in w).rsplit("/", 1)[1]


async def configured(session: Any, settings: Any) -> bool:
    return True


@pytest.fixture
def outbox(monkeypatch: pytest.MonkeyPatch) -> Outbox:
    box = Outbox()
    monkeypatch.setattr(mail_config, "is_configured", configured)
    monkeypatch.setattr(mailer, "send", box.send)

    async def load(session: Any, settings: Any) -> mailer.MailConfig:
        return mailer.MailConfig(host="mail", from_address="eoe@example.com", source="env")

    monkeypatch.setattr(mail_config, "load", load)
    return box


def accept(api: TestClient, token: str, **override: Any) -> Any:
    body = {"token": token, "full_name": "Nina New", "password": GOOD, **override}
    return api.post("/api/v1/auth/invite/accept", json=body)


def test_an_invited_person_chooses_a_password_and_is_in(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    sent = admin.post("/users/invites", json={"emails": ["Nina@Example.com"], "role": "editor"})
    assert sent.status_code == 201
    result = sent.json()[0]
    assert result["outcome"] == "emailed" and result["email"] == "nina@example.com"
    assert outbox.sent[0]["to"] == ["nina@example.com"]

    token = outbox.link("invite")
    shown = api.get(f"/api/v1/auth/links/{token}").json()
    assert shown == {
        "kind": "invite",
        "email": "nina@example.com",
        "role": "editor",
        "full_name": None,
    }

    joined = accept(api, token)
    assert joined.status_code == 201
    assert joined.json()["user"]["role"] == "editor"
    signed_in = api.post("/api/v1/auth/login", json={"email": "nina@example.com", "password": GOOD})
    assert signed_in.status_code == 200
    assert admin.get("/users/invites").json() == []  # no longer waiting


def test_a_link_works_once(api: TestClient, admin: Person, outbox: Outbox) -> None:
    admin.post("/users/invites", json={"emails": ["nina@example.com"]})
    token = outbox.link("invite")
    assert accept(api, token).status_code == 201
    again = accept(api, token)
    assert again.status_code == 404 and again.json()["error"]["code"] == "link_invalid"
    assert api.get(f"/api/v1/auth/links/{token}").status_code == 404


def test_a_new_invitation_replaces_the_old_link(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    admin.post("/users/invites", json={"emails": ["nina@example.com"]})
    old = outbox.link("invite")
    waiting = admin.get("/users/invites").json()
    resent = admin.post(f"/users/invites/{waiting[0]['id']}/resend")
    assert resent.status_code == 200 and resent.json()["outcome"] == "emailed"
    assert accept(api, old).status_code == 404
    assert accept(api, outbox.link("invite")).status_code == 201


def test_without_email_the_admin_gets_the_link_to_pass_on(
    api: TestClient, admin: Person, monkeypatch: pytest.MonkeyPatch
) -> None:
    async def not_configured(session: Any, settings: Any) -> bool:
        return False

    monkeypatch.setattr(mail_config, "is_configured", not_configured)
    result = admin.post("/users/invites", json={"emails": ["nina@example.com"]}).json()[0]
    assert result["outcome"] == "link" and "not set up" in result["detail"]
    token = result["link"].rsplit("/", 1)[1]
    assert result["link"].startswith("http://localhost:5173/invite/")
    assert accept(api, token).status_code == 201


def test_a_mail_failure_still_leaves_a_working_link(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    outbox.fail = "The mail server refused the sign-in."
    result = admin.post("/users/invites", json={"emails": ["nina@example.com"]}).json()[0]
    assert result["outcome"] == "link" and "refused" in result["detail"]
    assert accept(api, result["link"].rsplit("/", 1)[1]).status_code == 201


def test_people_who_already_have_an_account_are_not_invited_again(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    result = admin.post("/users/invites", json={"emails": ["asha@example.com"]}).json()[0]
    assert result["outcome"] == "exists" and outbox.sent == []


def test_a_revoked_invitation_stops_working(api: TestClient, admin: Person, outbox: Outbox) -> None:
    admin.post("/users/invites", json={"emails": ["nina@example.com"]})
    waiting = admin.get("/users/invites").json()
    assert admin.delete(f"/users/invites/{waiting[0]['id']}").status_code == 204
    assert accept(api, outbox.link("invite")).status_code == 404


def test_an_expired_invitation_stops_working(
    api: TestClient, admin: Person, outbox: Outbox, sql: Callable[..., list[Any]]
) -> None:
    admin.post("/users/invites", json={"emails": ["nina@example.com"]})
    sql("UPDATE account_links SET expires_at = now() - interval '1 minute'")
    assert accept(api, outbox.link("invite")).status_code == 404
    assert admin.get("/users/invites").json() == []


def test_only_admins_invite(api: TestClient, admin: Person, outbox: Outbox) -> None:
    viewer = person(api, admin, "vic@example.com", "viewer")
    assert viewer.post("/users/invites", json={"emails": ["x@example.com"]}).status_code == 403
    assert viewer.get("/users/invites").status_code == 403


def test_the_invited_password_follows_the_same_rules(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    admin.post("/users/invites", json={"emails": ["nina@example.com"]})
    token = outbox.link("invite")
    assert accept(api, token, password="short").status_code == 422
    assert accept(api, token, password="nina@example.com").status_code == 400
    assert accept(api, token).status_code == 201  # still usable after a mistake


# ── Forgot password ──────────────────────────────────────────────────────────


def test_a_forgotten_password_is_reset_from_the_email(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    other = person(api, admin, "vic@example.com", "viewer")
    asked = api.post("/api/v1/auth/forgot", json={"email": "vic@example.com"})
    assert asked.status_code == 204 and outbox.sent[0]["to"] == ["vic@example.com"]
    token = outbox.link("reset")
    assert api.get(f"/api/v1/auth/links/{token}").json()["full_name"] == "vic"

    done = api.post("/api/v1/auth/reset", json={"token": token, "password": GOOD})
    assert done.status_code == 200
    assert (
        api.post(
            "/api/v1/auth/login", json={"email": "vic@example.com", "password": "a-good-password"}
        ).status_code
        == 401
    )
    assert (
        api.post(
            "/api/v1/auth/login", json={"email": "vic@example.com", "password": GOOD}
        ).status_code
        == 200
    )
    assert other.get("/auth/me").status_code == 401  # the old session ended
    assert (
        api.post("/api/v1/auth/reset", json={"token": token, "password": GOOD}).status_code == 404
    )


def test_asking_for_a_reset_reveals_nothing_about_who_has_an_account(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    unknown = api.post("/api/v1/auth/forgot", json={"email": "nobody@example.com"})
    known = api.post("/api/v1/auth/forgot", json={"email": "asha@example.com"})
    assert unknown.status_code == known.status_code == 204
    assert [m["to"] for m in outbox.sent] == [["asha@example.com"]]


def test_reset_emails_are_limited_per_address(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    for _ in range(6):
        api.post("/api/v1/auth/forgot", json={"email": "asha@example.com"})
    assert len(outbox.sent) == 3


def test_a_turned_off_account_gets_no_reset(api: TestClient, admin: Person, outbox: Outbox) -> None:
    other = person(api, admin, "vic@example.com", "viewer")
    admin.patch(f"/users/{other.id}", json={"is_active": False})
    api.post("/api/v1/auth/forgot", json={"email": "vic@example.com"})
    assert outbox.sent == []


def test_an_invitation_link_cannot_reset_a_password(
    api: TestClient, admin: Person, outbox: Outbox
) -> None:
    admin.post("/users/invites", json={"emails": ["nina@example.com"]})
    token = outbox.link("invite")
    assert (
        api.post("/api/v1/auth/reset", json={"token": token, "password": GOOD}).status_code == 404
    )
