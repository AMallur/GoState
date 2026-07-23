from __future__ import annotations

import pytest

from app.core.security import (
    JWT_SECRET_ENV,
    hash_token,
    load_security_settings,
    verify_token_digest,
)

TEST_JWT_SECRET = "a-secure-test-secret-that-is-long-enough"  # noqa: S105


def test_security_bootstrap_fails_closed_without_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(JWT_SECRET_ENV, raising=False)

    with pytest.raises(RuntimeError):
        load_security_settings()


def test_security_bootstrap_loads_environment_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, TEST_JWT_SECRET)

    settings = load_security_settings()

    assert settings.jwt_secret_key == TEST_JWT_SECRET


def test_token_digest_verification_uses_constant_time_digest(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(JWT_SECRET_ENV, TEST_JWT_SECRET)
    settings = load_security_settings()
    digest = hash_token("developer-token", settings)

    assert verify_token_digest("developer-token", digest, settings) is True
    assert verify_token_digest("wrong-token", digest, settings) is False
