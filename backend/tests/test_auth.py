"""Sign-in, sessions, and accounts, end to end against the test database."""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx2
import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.v1.auth import REFRESH_COOKIE
from app.core.config import Settings
from app.core.security import hash_refresh_token
from app.main import create_app

pytestmark = pytest.mark.db

AUTH = "/api/v1/auth"
ADMIN = {
    "full_name": "Asha Admin",
    "email": "asha@example.com",
    "password": "correct-horse-battery",
}
VIEWER = {"full_name": "Vik Viewer", "email": "vik@example.com", "password": "viewer-password-1"}


@pytest.fixture
def api(settings: Settings, clean_db: None) -> Iterator[TestClient]:
    with TestClient(create_app(settings)) as client:
        yield client


def bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def setup_admin(api: TestClient) -> str:
    response = api.post(f"{AUTH}/setup", json=ADMIN)
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def add_user(api: TestClient, admin_token: str, **overrides: Any) -> dict[str, Any]:
    response = api.post("/api/v1/users", json={**VIEWER, **overrides}, headers=bearer(admin_token))
    assert response.status_code == 201, response.text
    return response.json()


def login(api: TestClient, email: str, password: str) -> httpx2.Response:
    return api.post(f"{AUTH}/login", json={"email": email, "password": password})


def refresh_with(api: TestClient, token: str) -> httpx2.Response:
    api.cookies.clear()
    return api.post(f"{AUTH}/refresh", headers={"Cookie": f"{REFRESH_COOKIE}={token}"})


def error_code(response: httpx2.Response) -> str:
    return response.json()["error"]["code"]


# ── First run ────────────────────────────────────────────────────────────────


def test_first_account_becomes_admin_and_setup_closes(api: TestClient) -> None:
    assert api.get(f"{AUTH}/setup").json() == {"needs_setup": True}

    response = api.post(f"{AUTH}/setup", json=ADMIN)

    assert response.status_code == 201
    body = response.json()
    assert body["user"]["role"] == "admin" and body["token_type"] == "bearer"
    cookie = response.headers["set-cookie"].lower()
    assert all(part in cookie for part in ("httponly", "samesite=strict", "path=/api/v1/auth"))
    assert api.get(f"{AUTH}/setup").json() == {"needs_setup": False}

    again = api.post(f"{AUTH}/setup", json={**ADMIN, "email": "other@example.com"})
    assert (again.status_code, error_code(again)) == (409, "setup_done")


def test_setup_rejects_short_passwords(api: TestClient) -> None:
    response = api.post(f"{AUTH}/setup", json={**ADMIN, "password": "short"})
    assert response.status_code == 422
    assert response.json()["error"]["details"][0]["field"] == "body.password"


def test_secrets_are_stored_only_as_hashes(api: TestClient, sql: Callable[..., Any]) -> None:
    response = api.post(f"{AUTH}/setup", json=ADMIN)
    cookie = response.cookies[REFRESH_COOKIE]

    [(password_hash,)] = sql("SELECT password_hash FROM users")
    [(token_hash,)] = sql("SELECT token_hash FROM refresh_tokens")
    assert password_hash.startswith("$argon2id$") and ADMIN["password"] not in password_hash
    assert token_hash == hash_refresh_token(cookie)


# ── Sign in ──────────────────────────────────────────────────────────────────


def test_login_with_the_right_password(api: TestClient) -> None:
    setup_admin(api)
    response = login(api, "ASHA@example.com ", ADMIN["password"])  # email case and spaces ignored

    assert response.status_code == 200, response.text
    me = api.get(f"{AUTH}/me", headers=bearer(response.json()["access_token"]))
    assert me.json()["email"] == "asha@example.com"
    assert me.json()["last_login_at"] is not None


def test_wrong_password_and_unknown_email_look_the_same(api: TestClient) -> None:
    setup_admin(api)
    wrong_password = login(api, ADMIN["email"], "not-the-password")
    unknown_email = login(api, "nobody@example.com", "not-the-password")

    for response in (wrong_password, unknown_email):
        assert response.status_code == 401
        assert error_code(response) == "invalid_credentials"
    assert wrong_password.json()["error"]["message"] == unknown_email.json()["error"]["message"]


def test_repeated_failures_lock_that_email_for_a_while(api: TestClient) -> None:
    setup_admin(api)
    for _ in range(5):
        assert login(api, ADMIN["email"], "wrong-password").status_code == 401

    blocked = login(api, ADMIN["email"], ADMIN["password"])  # even the right password waits

    assert blocked.status_code == 429
    assert int(blocked.headers["Retry-After"]) > 0
    assert login(api, "someone-else@example.com", "wrong-password").status_code == 401


def test_requests_without_a_valid_token_are_refused(api: TestClient, settings: Settings) -> None:
    setup_admin(api)
    secret = settings.secret_key.get_secret_value()
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": "x",
            "ver": 0,
            "type": "access",
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=1),
        },
        secret,
        algorithm="HS256",
    )
    cases = {
        "not_authenticated": {},
        "invalid_token": bearer("not-a-jwt"),
        "token_expired": bearer(expired),
    }
    for code, headers in cases.items():
        response = api.get(f"{AUTH}/me", headers=headers)
        assert (response.status_code, error_code(response)) == (401, code)


# ── Refresh and sign out ─────────────────────────────────────────────────────


def test_refresh_replaces_the_cookie_every_time(api: TestClient) -> None:
    first = api.post(f"{AUTH}/setup", json=ADMIN).cookies[REFRESH_COOKIE]

    refreshed = refresh_with(api, first)
    assert refreshed.status_code == 200
    second = refreshed.cookies[REFRESH_COOKIE]
    assert second != first
    assert (
        api.get(f"{AUTH}/me", headers=bearer(refreshed.json()["access_token"])).status_code == 200
    )

    # The old cookie right away: another tab raced us. Rejected, but the session survives.
    raced = refresh_with(api, first)
    assert (raced.status_code, error_code(raced)) == (401, "refresh_superseded")
    assert refresh_with(api, second).status_code == 200


def test_reusing_an_old_refresh_token_later_ends_the_whole_session(
    api: TestClient, sql: Callable[..., Any]
) -> None:
    first = api.post(f"{AUTH}/setup", json=ADMIN).cookies[REFRESH_COOKIE]
    second = refresh_with(api, first).cookies[REFRESH_COOKIE]
    sql(
        "UPDATE refresh_tokens SET revoked_at = revoked_at - interval '1 minute' "
        "WHERE token_hash = :hash",
        {"hash": hash_refresh_token(first)},
    )

    stolen = refresh_with(api, first)  # looks like a copied token being replayed

    assert (stolen.status_code, error_code(stolen)) == (401, "session_expired")
    legit = refresh_with(api, second)
    assert (legit.status_code, error_code(legit)) == (401, "session_expired")


def test_a_token_from_a_revoked_session_is_not_mistaken_for_a_tab_race(api: TestClient) -> None:
    first = api.post(f"{AUTH}/setup", json=ADMIN).cookies[REFRESH_COOKIE]
    second = refresh_with(api, first).cookies[REFRESH_COOKIE]
    api.cookies.clear()
    api.post(f"{AUTH}/logout", headers={"Cookie": f"{REFRESH_COOKIE}={second}"})

    # Seconds after the rotation, but the session is gone: "sign in again", not "retry".
    stale = refresh_with(api, first)
    assert (stale.status_code, error_code(stale)) == (401, "session_expired")


def test_logout_ends_the_session(api: TestClient) -> None:
    cookie = api.post(f"{AUTH}/setup", json=ADMIN).cookies[REFRESH_COOKIE]

    response = api.post(f"{AUTH}/logout")

    assert response.status_code == 204
    assert "max-age=0" in response.headers["set-cookie"].lower()
    assert refresh_with(api, cookie).status_code == 401


def test_changing_password_signs_out_other_sessions(api: TestClient) -> None:
    old_token = setup_admin(api)
    other_device = login(api, ADMIN["email"], ADMIN["password"]).cookies[REFRESH_COOKIE]

    wrong = api.post(
        f"{AUTH}/password",
        json={"current_password": "nope", "new_password": "a-brand-new-password"},
        headers=bearer(old_token),
    )
    assert (wrong.status_code, error_code(wrong)) == (400, "wrong_password")

    changed = api.post(
        f"{AUTH}/password",
        json={"current_password": ADMIN["password"], "new_password": "a-brand-new-password"},
        headers=bearer(old_token),
    )
    assert changed.status_code == 200
    assert api.get(f"{AUTH}/me", headers=bearer(old_token)).status_code == 401
    assert api.get(f"{AUTH}/me", headers=bearer(changed.json()["access_token"])).status_code == 200
    assert refresh_with(api, other_device).status_code == 401
    assert login(api, ADMIN["email"], "a-brand-new-password").status_code == 200


# ── Accounts and roles ───────────────────────────────────────────────────────


def test_admin_adds_users_and_roles_apply_immediately(api: TestClient) -> None:
    admin = setup_admin(api)
    viewer_id = add_user(api, admin)["id"]
    duplicate = api.post("/api/v1/users", json=VIEWER, headers=bearer(admin))
    assert (duplicate.status_code, error_code(duplicate)) == (409, "email_taken")
    assert len(api.get("/api/v1/users", headers=bearer(admin)).json()) == 2

    viewer = login(api, VIEWER["email"], VIEWER["password"]).json()["access_token"]
    for path in ("/api/v1/users", "/api/v1/admin/llm/status"):
        response = api.get(path, headers=bearer(viewer))
        assert (response.status_code, error_code(response)) == (403, "forbidden")

    promoted = api.patch(
        f"/api/v1/users/{viewer_id}", json={"role": "editor"}, headers=bearer(admin)
    )
    assert promoted.json()["role"] == "editor"
    assert api.get(f"{AUTH}/me", headers=bearer(viewer)).json()["role"] == "editor"


def test_turning_a_user_off_signs_them_out_at_once(api: TestClient) -> None:
    admin = setup_admin(api)
    viewer_id = add_user(api, admin)["id"]
    viewer = login(api, VIEWER["email"], VIEWER["password"]).json()["access_token"]

    api.patch(f"/api/v1/users/{viewer_id}", json={"is_active": False}, headers=bearer(admin))

    response = api.get(f"{AUTH}/me", headers=bearer(viewer))
    assert (response.status_code, error_code(response)) == (401, "session_expired")
    again = login(api, VIEWER["email"], VIEWER["password"])
    assert (again.status_code, error_code(again)) == (403, "account_disabled")


def test_the_last_admin_cannot_be_removed(api: TestClient) -> None:
    admin = setup_admin(api)
    my_id = api.get(f"{AUTH}/me", headers=bearer(admin)).json()["id"]

    for change in ({"role": "viewer"}, {"is_active": False}):
        response = api.patch(f"/api/v1/users/{my_id}", json=change, headers=bearer(admin))
        assert (response.status_code, error_code(response)) == (409, "last_admin")

    add_user(api, admin, email="second@example.com", role="admin")
    demoted = api.patch(f"/api/v1/users/{my_id}", json={"role": "viewer"}, headers=bearer(admin))
    assert demoted.status_code == 200
