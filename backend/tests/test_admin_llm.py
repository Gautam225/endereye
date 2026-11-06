from collections.abc import Iterator

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from app.api.deps import require_admin
from app.core.config import Settings
from app.db.models import Role, User
from app.main import create_app


def admin_app(settings: Settings) -> FastAPI:
    """App whose admin check always passes (sign-in itself is tested in test_auth.py)."""
    app = create_app(settings)
    stand_in = User(email="admin@example.com", full_name="Admin", role=Role.ADMIN)
    app.dependency_overrides[require_admin] = lambda: stand_in
    return app


@pytest.fixture
def admin_client(settings: Settings) -> Iterator[TestClient]:
    with TestClient(admin_app(settings)) as client:
        yield client


def test_status_lists_providers_with_masked_keys(settings: Settings) -> None:
    secret = "sk-or-v1-a-very-secret-value-1234"
    custom = settings.model_copy(
        update={
            "openrouter_api_keys": [SecretStr(secret)],
            # .invalid never resolves, so the background model check fails fast offline.
            "openrouter_base_url": "https://openrouter.invalid/api/v1",
        }
    )
    with TestClient(admin_app(custom)) as client:
        response = client.get("/api/v1/admin/llm/status")

    assert response.status_code == 200
    assert secret not in response.text
    openrouter, groq = response.json()["providers"]
    assert (openrouter["name"], openrouter["role"], openrouter["configured"]) == (
        "openrouter",
        "primary",
        True,
    )
    assert openrouter["keys"][0]["masked"] == "sk-or-...1234"
    assert openrouter["keys"][0]["state"] == "ready"
    assert (groq["role"], groq["configured"], groq["keys"]) == ("fallback", False, [])


def test_admin_routes_need_a_signed_in_user(client: TestClient) -> None:
    response = client.get("/api/v1/admin/llm/status")
    assert response.status_code == 401
    assert response.json()["error"]["code"] == "not_authenticated"
    assert response.headers["WWW-Authenticate"] == "Bearer"
