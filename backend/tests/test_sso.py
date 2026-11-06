"""Single sign-on (OpenID Connect), against a pretend identity provider that signs real tokens
(needs the test database)."""

import time
from collections.abc import Callable, Iterator
from typing import Any
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.core.config import Settings
from app.main import create_app
from app.services import sso

pytestmark = pytest.mark.db

ISSUER = "https://idp.example.com"
CLIENT_ID = "eye-of-ender"
KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
JWK = jwt.algorithms.RSAAlgorithm.to_jwk(KEY.public_key(), as_dict=True) | {
    "kid": "k1",
    "alg": "RS256",
    "use": "sig",
}
PROVIDER = sso.Provider(
    issuer=ISSUER,
    authorization_endpoint=f"{ISSUER}/authorize",
    token_endpoint=f"{ISSUER}/token",
    jwks_uri=f"{ISSUER}/keys",
)


class Idp:
    """What the provider will hand back for the next code exchange."""

    def __init__(self) -> None:
        self.claims: dict[str, Any] = {}
        self.status = 200
        self.nonce = ""

    def id_token(self, **override: Any) -> str:
        now = int(time.time())
        claims = {
            "iss": ISSUER,
            "aud": CLIENT_ID,
            "sub": "u-1",
            "exp": now + 300,
            "iat": now,
            "nonce": self.nonce,
            "email": "sam@example.com",
            "email_verified": True,
            "name": "Sam Single",
            **self.claims,
            **override,
        }
        claims = {k: v for k, v in claims.items() if v is not None}
        return jwt.encode(claims, KEY, algorithm="RS256", headers={"kid": "k1"})


@pytest.fixture
def idp(monkeypatch: pytest.MonkeyPatch) -> Idp:
    provider = Idp()

    async def discover(settings: Settings) -> sso.Provider:
        return PROVIDER

    async def get_json(url: str) -> dict[str, Any]:
        return {"keys": [JWK]}

    class Response:
        def __init__(self) -> None:
            self.status_code = provider.status

        def json(self) -> dict[str, Any]:
            return {"id_token": provider.id_token()}

    class FakeClient:
        def __init__(self, **kwargs: Any) -> None:
            pass

        async def __aenter__(self) -> "FakeClient":
            return self

        async def __aexit__(self, *args: Any) -> None:
            return None

        async def post(self, url: str, **kwargs: Any) -> Response:
            assert url == PROVIDER.token_endpoint
            assert kwargs["data"]["code_verifier"]  # PKCE is used
            return Response()

    monkeypatch.setattr(sso, "discover", discover)
    monkeypatch.setattr(sso, "_get_json", get_json)
    monkeypatch.setattr(sso.httpx2, "AsyncClient", FakeClient)
    monkeypatch.setattr(sso, "_keys", None)
    return provider


def build(settings: Settings, **extra: Any) -> Iterator[TestClient]:
    custom = settings.model_copy(
        update={
            "sso_issuer": ISSUER,
            "sso_client_id": CLIENT_ID,
            "sso_client_secret": SecretStr("secret"),
            "public_url": "http://app.test",
            **extra,
        }
    )
    with TestClient(create_app(custom), follow_redirects=False) as client:
        yield client


@pytest.fixture
def api(settings: Settings, clean_db: None) -> Iterator[TestClient]:
    yield from build(settings)


def sign_in(api: TestClient, idp: Idp, next_path: str = "/reports") -> Any:
    """Click the company button, come back from the provider with a code."""
    begun = api.get("/api/v1/auth/sso/start", params={"next": next_path})
    assert begun.status_code == 303
    query = parse_qs(urlparse(begun.headers["location"]).query)
    assert query["code_challenge_method"] == ["S256"]
    assert query["redirect_uri"] == ["http://app.test/api/v1/auth/sso/callback"]
    idp.nonce = query["nonce"][0]
    return api.get("/api/v1/auth/sso/callback", params={"code": "abc", "state": query["state"][0]})


def error_of(response: Any) -> str:
    assert response.status_code == 303
    return parse_qs(urlparse(response.headers["location"]).query)["sso_error"][0]


def test_the_sign_in_page_is_told_whether_sso_is_on(api: TestClient) -> None:
    body = api.get("/api/v1/auth/sso").json()
    assert body == {"enabled": True, "name": "Single sign-on", "password_login": True}


def test_without_settings_sso_is_off(settings: Settings, clean_db: None) -> None:
    off = settings.model_copy(update={"sso_issuer": "", "sso_client_id": ""})
    with TestClient(create_app(off), follow_redirects=False) as api:
        assert api.get("/api/v1/auth/sso").json()["enabled"] is False
        assert error_of(api.get("/api/v1/auth/sso/start")) == "not_enabled"


def test_a_new_person_gets_an_account_and_a_session(
    api: TestClient, idp: Idp, sql: Callable[..., list[Any]]
) -> None:
    done = sign_in(api, idp)
    assert done.status_code == 303
    assert done.headers["location"] == "http://app.test/reports"
    assert "eoe_refresh=" in done.headers.get_list("set-cookie")[0]

    session = api.post("/api/v1/auth/refresh").json()  # what the app does when it opens
    assert session["user"]["email"] == "sam@example.com"
    assert session["user"]["role"] == "viewer"
    assert [row[0] for row in sql("SELECT sso_subject FROM users")] == [f"{ISSUER}|u-1"]


def test_an_admin_made_account_is_linked_by_email(
    settings: Settings, clean_db: None, idp: Idp
) -> None:
    for api in build(settings):
        api.post(
            "/api/v1/auth/setup",
            json={
                "full_name": "Sam",
                "email": "sam@example.com",
                "password": "correct-horse-battery",
            },
        )
        api.cookies.clear()
        sign_in(api, idp)
        me = api.post("/api/v1/auth/refresh").json()["user"]
        assert me["email"] == "sam@example.com"
        assert me["role"] == "admin"  # their own account, not a new viewer


def test_only_listed_domains_may_sign_in(settings: Settings, clean_db: None, idp: Idp) -> None:
    for api in build(settings, sso_allowed_domains=["corp.com"]):
        assert error_of(sign_in(api, idp)) == "domain_not_allowed"


def test_accounts_can_be_made_by_admins_only(settings: Settings, clean_db: None, idp: Idp) -> None:
    for api in build(settings, sso_auto_create=False):
        assert error_of(sign_in(api, idp)) == "no_account"


def test_an_unverified_email_is_not_trusted(api: TestClient, idp: Idp) -> None:
    idp.claims = {"email_verified": False}
    assert error_of(sign_in(api, idp)) == "no_email"


def test_a_token_for_another_app_or_nonce_is_refused(api: TestClient, idp: Idp) -> None:
    idp.claims = {"aud": "someone-else"}
    assert error_of(sign_in(api, idp)) == "invalid_token"
    idp.claims = {}
    begun = api.get("/api/v1/auth/sso/start")
    state = parse_qs(urlparse(begun.headers["location"]).query)["state"][0]
    idp.nonce = "not-the-one-we-sent"
    assert error_of(api.get("/api/v1/auth/sso/callback", params={"code": "x", "state": state})) == (
        "invalid_token"
    )


def test_a_forged_state_or_a_missing_cookie_is_refused(api: TestClient, idp: Idp) -> None:
    api.get("/api/v1/auth/sso/start")
    assert error_of(api.get("/api/v1/auth/sso/callback", params={"code": "x", "state": "no"})) == (
        "expired"
    )
    api.cookies.clear()
    assert error_of(api.get("/api/v1/auth/sso/callback", params={"code": "x", "state": "no"})) == (
        "expired"
    )


def test_a_refused_exchange_or_a_denied_person_comes_back_with_a_message(
    api: TestClient, idp: Idp
) -> None:
    idp.status = 400
    assert error_of(sign_in(api, idp)) == "rejected"
    denied = api.get("/api/v1/auth/sso/callback", params={"error": "access_denied"})
    assert error_of(denied) == "denied"


def test_a_turned_off_account_cannot_come_in(
    api: TestClient, idp: Idp, sql: Callable[..., list[Any]]
) -> None:
    sign_in(api, idp)
    sql("UPDATE users SET is_active = false")
    assert error_of(sign_in(api, idp)) == "account_disabled"


def test_the_return_address_cannot_leave_the_app(api: TestClient, idp: Idp) -> None:
    done = sign_in(api, idp, next_path="//evil.example.com")
    assert done.headers["location"] == "http://app.test/"
    assert sso.safe_next("https://evil.example.com") == "/"
    assert sso.safe_next("/\\evil") == "/"
    assert sso.safe_next("/spaces/1/chat?x=1") == "/spaces/1/chat?x=1"


def test_the_password_form_can_be_turned_off(settings: Settings, clean_db: None) -> None:
    for api in build(settings, sso_password_login=False):
        assert api.get("/api/v1/auth/sso").json()["password_login"] is False
        refused = api.post(
            "/api/v1/auth/login", json={"email": "a@example.com", "password": "whatever-it-is"}
        )
        assert refused.status_code == 403
        assert refused.json()["error"]["code"] == "password_login_disabled"
