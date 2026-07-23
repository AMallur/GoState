from __future__ import annotations

import pytest

from app.cli import build_workspace_footprint, hash_text, normalize_workspace_id, validate_http_url


def test_build_workspace_footprint_hashes_files_and_environment(
    tmp_path,
    monkeypatch,
) -> None:
    workspace = tmp_path / "demo workspace"
    workspace.mkdir()
    source_file = workspace / "main.py"
    source_file.write_text("print('hello')\n", encoding="utf-8")
    monkeypatch.setenv("GOSTATE_TEST_TOKEN", "raw-secret-value")

    footprint = build_workspace_footprint(
        root=workspace,
        max_files=10,
        max_file_bytes=100_000,
        env_names=("GOSTATE_TEST_TOKEN",),
    )

    assert footprint.root_path == str(workspace)
    assert len(footprint.files) == 1
    assert footprint.files[0].path == str(source_file)
    assert footprint.files[0].content_sha256 == hash_text("print('hello')\n")
    assert len(footprint.environment) == 1
    assert footprint.environment[0].name == "GOSTATE_TEST_TOKEN"
    assert footprint.environment[0].value_sha256 == hash_text("raw-secret-value")
    assert footprint.environment[0].is_secret is True
    assert "raw-secret-value" not in footprint.model_dump_json()


def test_build_workspace_footprint_skips_large_files(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    large_file = workspace / "large.bin"
    large_file.write_bytes(b"x" * 32)

    footprint = build_workspace_footprint(
        root=workspace,
        max_files=10,
        max_file_bytes=4,
        env_names=(),
    )

    assert footprint.files == ()


def test_normalize_workspace_id_produces_contract_safe_value() -> None:
    assert normalize_workspace_id("demo workspace!") == "demo-workspace-"


def test_validate_http_url_rejects_non_http_schemes() -> None:
    with pytest.raises(ValueError):
        validate_http_url("file:///tmp/payload.json")
