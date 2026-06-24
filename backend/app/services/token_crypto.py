"""Small encrypted-token helper for OAuth secrets stored in Postgres."""
from __future__ import annotations

import base64
import binascii
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from ..config import Settings, get_settings


class TokenCipher:
    def __init__(self, secret: str):
        if not secret:
            raise ValueError("A token encryption secret is required")
        self._fernet = Fernet(_fernet_key(secret))

    def encrypt(self, value: str) -> str:
        if not value:
            return ""
        return self._fernet.encrypt(value.encode("utf-8")).decode("ascii")

    def decrypt(self, value: str) -> str:
        if not value:
            return ""
        try:
            return self._fernet.decrypt(value.encode("ascii")).decode("utf-8")
        except (InvalidToken, UnicodeError) as exc:
            raise ValueError("Stored token could not be decrypted") from exc


def _fernet_key(secret: str) -> bytes:
    candidate = secret.encode("utf-8")
    try:
        if len(base64.urlsafe_b64decode(candidate)) == 32:
            return candidate
    except (binascii.Error, ValueError):
        pass
    return base64.urlsafe_b64encode(hashlib.sha256(candidate).digest())


def get_token_cipher(settings: Settings | None = None) -> TokenCipher:
    settings = settings or get_settings()
    return TokenCipher(settings.gmail_token_encryption_key or settings.secret_key)
