from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import create_app
from app.models.user import TEST_TENANT_ID, TEST_USER_ID


def test_dev_console_disabled_by_default() -> None:
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 404
    assert response.json()["type"] == "https://gostate.local/problems/dev-mode-disabled"


def test_dev_test_user_bootstrap_enabled(monkeypatch) -> None:
    monkeypatch.setenv("GOSTATE_DEV_MODE", "true")
    client = TestClient(create_app())

    response = client.post("/dev/test-user")

    assert response.status_code == 200
    body = response.json()
    assert body["created"] is True
    assert body["user"]["user_id"] == str(TEST_USER_ID)
    assert body["user"]["tenant_id"] == str(TEST_TENANT_ID)


def test_dev_console_serves_browser_test_app(monkeypatch) -> None:
    monkeypatch.setenv("GOSTATE_DEV_MODE", "true")
    client = TestClient(create_app())

    response = client.get("/")

    assert response.status_code == 200
    assert "GoState Test Console" in response.text
