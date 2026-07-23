"""Fail-closed security bootstrap and token primitives."""

from __future__ import annotations

import hashlib
import hmac
import os
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field

JWT_SECRET_ENV: Final[str] = "JWT_SECRET_KEY"
MIN_SECRET_LENGTH: Final[int] = 32

SecretKey = Annotated[str, Field(min_length=MIN_SECRET_LENGTH)]


class SecuritySettings(BaseModel):
    """Environment-bound security settings."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    jwt_secret_key: SecretKey


def load_security_settings() -> SecuritySettings:
    """Load security settings or abort application bootstrap."""

    raw_secret = os.getenv(JWT_SECRET_ENV)
    if raw_secret is None or raw_secret.strip() == "":
        raise RuntimeError(f"{JWT_SECRET_ENV} must be set before GoState can boot")
    return SecuritySettings(jwt_secret_key=raw_secret)


def hash_token(token: str, settings: SecuritySettings) -> str:
    """Return a stable HMAC-SHA256 token digest suitable for constant-time comparison."""

    return hmac.new(
        settings.jwt_secret_key.encode("utf-8"),
        token.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_token_digest(token: str, expected_digest: str, settings: SecuritySettings) -> bool:
    """Validate a token digest without leaking timing information."""

    candidate_digest = hash_token(token, settings)
    return hmac.compare_digest(candidate_digest, expected_digest)
