"""Encrypting secrets that must be read back later (database passwords of connections).

Passwords of people are hashed (Argon2) because nobody needs them back. A database password is
different: the app has to send it to the database, so it is stored encrypted instead.

- AES-256-GCM. Every value gets a fresh random nonce, and is bound to what it belongs to
  (`context`, e.g. the connection's id), so a value copied into another row does not decrypt.
- The key comes only from the environment (CONNECTION_ENCRYPTION_KEY), never from the database
  and never from SECRET_KEY, so a leaked database dump alone reveals nothing.
- Rotation: put the new key in CONNECTION_ENCRYPTION_KEY and the old one in
  CONNECTION_ENCRYPTION_KEY_PREVIOUS. Old values still decrypt and are re-encrypted when saved.
- Stored form: "v1.<key id>.<base64url(nonce + ciphertext)>". The key id is a short hash of the
  key, so it says which key was used without revealing it.
"""

import base64
import hashlib
import os
from dataclasses import dataclass

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.core.errors import AppError

VERSION = "v1"
KEY_BYTES = 32
NONCE_BYTES = 12


class VaultError(AppError):
    """The secret could not be stored or read. The message never includes the secret."""

    status_code = 500
    code = "vault_error"


class VaultNotConfiguredError(AppError):
    status_code = 503
    code = "vault_not_configured"


def generate_key() -> str:
    """A new key, to be put in CONNECTION_ENCRYPTION_KEY."""
    return base64.urlsafe_b64encode(os.urandom(KEY_BYTES)).decode()


def _decode_key(text: str) -> bytes:
    try:
        raw = base64.urlsafe_b64decode(text.strip() + "=" * (-len(text.strip()) % 4))
    except ValueError:
        raise ValueError("it is not valid base64") from None
    if len(raw) != KEY_BYTES:
        raise ValueError(f"it must decode to {KEY_BYTES} bytes")
    return raw


def check_key(text: str) -> str:
    """Raises ValueError (without the key in the message) when the key is not usable."""
    _decode_key(text)
    return text


def _key_id(key: bytes) -> str:
    return hashlib.sha256(b"eye-of-ender/key-id" + key).hexdigest()[:8]


@dataclass(frozen=True, slots=True)
class Vault:
    """Encrypts with the current key; decrypts with the current or the previous one."""

    keys: dict[str, bytes]  # key id -> key
    current: str  # the key id used to encrypt

    @classmethod
    def from_keys(cls, current: str | None, previous: str | None = None) -> "Vault":
        if not current:
            raise VaultNotConfiguredError(
                "Connections need CONNECTION_ENCRYPTION_KEY in .env. Make one with: "
                'python -c "from app.core.vault import generate_key; print(generate_key())"'
            )
        try:
            key = _decode_key(current)
        except ValueError as exc:
            raise VaultNotConfiguredError(
                f"CONNECTION_ENCRYPTION_KEY is not a valid key: {exc}."
            ) from None
        keys = {_key_id(key): key}
        if previous:
            try:
                old = _decode_key(previous)
            except ValueError as exc:
                raise VaultNotConfiguredError(
                    f"CONNECTION_ENCRYPTION_KEY_PREVIOUS is not a valid key: {exc}."
                ) from None
            keys[_key_id(old)] = old
        return cls(keys=keys, current=_key_id(key))

    def encrypt(self, secret: str, context: str) -> str:
        nonce = os.urandom(NONCE_BYTES)
        sealed = AESGCM(self.keys[self.current]).encrypt(nonce, secret.encode(), context.encode())
        body = base64.urlsafe_b64encode(nonce + sealed).decode()
        return f"{VERSION}.{self.current}.{body}"

    def decrypt(self, stored: str, context: str) -> str:
        try:
            version, key_id, body = stored.split(".", 2)
            key = self.keys[key_id]
            if version != VERSION:
                raise KeyError(version)
            raw = base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))
            nonce, sealed = raw[:NONCE_BYTES], raw[NONCE_BYTES:]
            return AESGCM(key).decrypt(nonce, sealed, context.encode()).decode()
        except (ValueError, KeyError, InvalidTag):
            # Never say which part failed or include any of the value.
            raise VaultError(
                "A stored secret could not be decrypted. Check CONNECTION_ENCRYPTION_KEY "
                "(and CONNECTION_ENCRYPTION_KEY_PREVIOUS after a key change)."
            ) from None

    def needs_rotation(self, stored: str) -> bool:
        """True when the value was encrypted with an older key."""
        parts = stored.split(".", 2)
        return len(parts) == 3 and parts[1] != self.current
