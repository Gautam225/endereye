import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from app.core.config import load_settings
from app.core.rate_limit import SlidingWindowLimiter
from app.core.security import (
    create_access_token,
    decode_access_token,
    hash_password,
    hash_refresh_token,
    new_refresh_token,
    verify_password,
)

SETTINGS = load_settings(_env_file=None, postgres_password="x", secret_key="k" * 40)


@pytest.mark.anyio
async def test_passwords_are_hashed_with_argon2id_and_verified() -> None:
    stored = await hash_password("correct horse battery")
    assert stored.startswith("$argon2id$")
    assert (await verify_password("correct horse battery", stored))[0] is True
    assert (await verify_password("wrong horse battery", stored))[0] is False
    assert (await verify_password("anything at all", None))[0] is False  # unknown user


def test_access_token_round_trip() -> None:
    user_id = uuid.uuid4()
    token, expires_in = create_access_token(user_id, 3, SETTINGS)
    claims = decode_access_token(token, SETTINGS)
    assert (claims.user_id, claims.token_version, expires_in) == (user_id, 3, 15 * 60)


def test_access_token_signed_with_another_secret_is_rejected() -> None:
    other = load_settings(_env_file=None, postgres_password="x", secret_key="z" * 40)
    token, _ = create_access_token(uuid.uuid4(), 0, other)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token, SETTINGS)


def test_tampered_or_wrong_type_tokens_are_rejected() -> None:
    token, _ = create_access_token(uuid.uuid4(), 0, SETTINGS)
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(token[:-2] + ("AA" if not token.endswith("AA") else "BB"), SETTINGS)

    secret = SETTINGS.secret_key.get_secret_value()
    now = datetime.now(UTC)
    refresh_like = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "ver": 0,
            "type": "refresh",
            "iat": now,
            "exp": now + timedelta(minutes=5),
        },
        secret,
        algorithm="HS256",
    )
    with pytest.raises(jwt.InvalidTokenError):
        decode_access_token(refresh_like, SETTINGS)


def test_expired_access_token_is_reported_as_expired() -> None:
    now = datetime.now(UTC)
    expired = jwt.encode(
        {
            "sub": str(uuid.uuid4()),
            "ver": 0,
            "type": "access",
            "iat": now - timedelta(hours=1),
            "exp": now - timedelta(minutes=5),
        },
        SETTINGS.secret_key.get_secret_value(),
        algorithm="HS256",
    )
    with pytest.raises(jwt.ExpiredSignatureError):
        decode_access_token(expired, SETTINGS)


def test_refresh_tokens_are_random_and_stored_only_as_hashes() -> None:
    token_a, hash_a = new_refresh_token()
    token_b, _ = new_refresh_token()
    assert token_a != token_b and len(token_a) >= 43
    assert hash_a == hash_refresh_token(token_a) and token_a not in hash_a


def test_limiter_blocks_after_the_limit_until_the_window_passes() -> None:
    now = [0.0]
    limiter = SlidingWindowLimiter(limit=3, window_seconds=60, clock=lambda: now[0])
    for _ in range(3):
        assert limiter.retry_after("k") == 0
        limiter.hit("k")
    assert limiter.retry_after("k") == 60
    now[0] = 45
    assert limiter.retry_after("k") == 15
    now[0] = 61
    assert limiter.retry_after("k") == 0
    limiter.hit("k")
    limiter.reset("k")
    assert limiter.retry_after("k") == 0
