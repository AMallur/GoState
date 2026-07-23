"""Local GoState capture and restore CLI."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Final
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen
from uuid import UUID, uuid4

from pydantic import ValidationError

from app.models import (
    ContextAttribute,
    ContextCaptureRequest,
    ContextRestorePlan,
    EnvironmentVariable,
    FileSystemEntry,
    FileSystemNodeType,
    TerminalProcess,
    WorkspaceFootprint,
)

DEFAULT_API_URL: Final[str] = "http://127.0.0.1:8000"
DEFAULT_ENV_NAMES: Final[tuple[str, ...]] = (
    "CONDA_PREFIX",
    "HOME",
    "NODE_ENV",
    "PATH",
    "PWD",
    "PYTHONPATH",
    "SHELL",
    "USER",
    "VIRTUAL_ENV",
)
SKIPPED_DIR_NAMES: Final[frozenset[str]] = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "node_modules",
        "venv",
    }
)
SECRET_NAME_FRAGMENTS: Final[tuple[str, ...]] = (
    "KEY",
    "SECRET",
    "TOKEN",
    "PASSWORD",
    "PASS",
    "CREDENTIAL",
)


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    try:
        if args.command == "health":
            print_json(api_get(f"{args.api_url}/health"))
        elif args.command == "capture":
            capture(args)
        elif args.command == "restore":
            restore(args)
        else:
            parser.error("unknown command")
    except (HTTPError, URLError, ValidationError, ValueError) as exc:
        print(f"gostate: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gostate",
        description="Capture and inspect GoState workspace context snapshots.",
    )
    parser.set_defaults(api_url=DEFAULT_API_URL)
    subparsers = parser.add_subparsers(dest="command", required=True)

    health_parser = subparsers.add_parser("health", help="Check the GoState API health endpoint.")
    add_api_url_argument(health_parser)

    capture_parser = subparsers.add_parser("capture", help="Capture a local workspace footprint.")
    add_api_url_argument(capture_parser)
    capture_parser.add_argument("root", type=Path, help="Workspace root path to capture.")
    capture_parser.add_argument(
        "--owner-user-id",
        type=UUID,
        default=uuid_from_env("GOSTATE_OWNER_USER_ID"),
        help="Owner user UUID. Defaults to GOSTATE_OWNER_USER_ID or a generated UUID.",
    )
    capture_parser.add_argument(
        "--tenant-id",
        type=UUID,
        default=uuid_from_env("GOSTATE_TENANT_ID"),
        help="Tenant UUID. Defaults to GOSTATE_TENANT_ID or a generated UUID.",
    )
    capture_parser.add_argument(
        "--workspace-id",
        default=None,
        help="Workspace identifier. Defaults to the root directory name.",
    )
    capture_parser.add_argument(
        "--max-files",
        type=int,
        default=500,
        help="Maximum number of files to hash and include.",
    )
    capture_parser.add_argument(
        "--max-file-bytes",
        type=int,
        default=5_000_000,
        help="Maximum file size to hash and include.",
    )
    capture_parser.add_argument(
        "--env",
        action="append",
        default=[],
        help="Environment variable name to include as a SHA-256 digest.",
    )

    restore_parser = subparsers.add_parser("restore", help="Fetch a restore plan for a state ID.")
    add_api_url_argument(restore_parser)
    restore_parser.add_argument("state_id", type=UUID, help="Captured context state UUID.")

    return parser


def add_api_url_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--api-url",
        default=DEFAULT_API_URL,
        help=f"GoState API base URL. Defaults to {DEFAULT_API_URL}.",
    )


def uuid_from_env(name: str) -> UUID:
    raw_value = os.getenv(name)
    if raw_value:
        return UUID(raw_value)
    return uuid4()


def capture(args: argparse.Namespace) -> None:
    root = args.root.resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"workspace root must be an existing directory: {root}")

    workspace_id = args.workspace_id or normalize_workspace_id(root.name)
    footprint = build_workspace_footprint(
        root=root,
        max_files=args.max_files,
        max_file_bytes=args.max_file_bytes,
        env_names=tuple(args.env) if args.env else DEFAULT_ENV_NAMES,
    )
    request = ContextCaptureRequest(
        owner_user_id=args.owner_user_id,
        tenant_id=args.tenant_id,
        workspace_id=workspace_id,
        payload=footprint,
    )
    response = api_post_json(f"{args.api_url}/contexts", request.model_dump_json())
    print_json(response)


def restore(args: argparse.Namespace) -> None:
    response = api_post_json(f"{args.api_url}/contexts/{args.state_id}/restore", "{}")
    restore_plan = ContextRestorePlan.model_validate_json(json.dumps(response))
    print_json(restore_plan.model_dump(mode="json"))


def build_workspace_footprint(
    *,
    root: Path,
    max_files: int,
    max_file_bytes: int,
    env_names: Sequence[str],
) -> WorkspaceFootprint:
    now = datetime.now(UTC)
    files = tuple(iter_file_entries(root, max_files=max_files, max_file_bytes=max_file_bytes))
    environment = tuple(iter_environment_entries(env_names))
    process = current_process_entry(root=root, now=now, environment=environment)
    attributes = (
        ContextAttribute(key="capture.source", value="gostate-cli"),
        ContextAttribute(key="capture.file_limit", value=max_files),
    )
    return WorkspaceFootprint(
        root_path=str(root),
        files=files,
        environment=environment,
        processes=(process,),
        attributes=attributes,
    )


def iter_file_entries(
    root: Path,
    *,
    max_files: int,
    max_file_bytes: int,
) -> Iterable[FileSystemEntry]:
    emitted = 0
    for path in sorted(root.rglob("*")):
        if emitted >= max_files:
            break
        if should_skip_path(path):
            continue
        try:
            stat = path.lstat()
        except OSError:
            continue

        modified_at = datetime.fromtimestamp(stat.st_mtime, UTC)
        if path.is_symlink():
            yield FileSystemEntry(
                path=str(path),
                node_type=FileSystemNodeType.SYMLINK,
                size_bytes=0,
                modified_at=modified_at,
            )
            emitted += 1
        elif path.is_file() and stat.st_size <= max_file_bytes:
            yield FileSystemEntry(
                path=str(path),
                node_type=FileSystemNodeType.FILE,
                size_bytes=stat.st_size,
                content_sha256=hash_file(path),
                modified_at=modified_at,
            )
            emitted += 1


def should_skip_path(path: Path) -> bool:
    return any(part in SKIPPED_DIR_NAMES for part in path.parts)


def iter_environment_entries(env_names: Sequence[str]) -> Iterable[EnvironmentVariable]:
    seen: set[str] = set()
    for name in env_names:
        if name in seen or name not in os.environ:
            continue
        seen.add(name)
        value = os.environ[name]
        yield EnvironmentVariable(
            name=name,
            value_sha256=hash_text(value),
            is_secret=is_secret_name(name),
        )


def current_process_entry(
    *,
    root: Path,
    now: datetime,
    environment: Sequence[EnvironmentVariable],
) -> TerminalProcess:
    command = " ".join(sys.argv) or "python"
    environment_fingerprint = "|".join(f"{item.name}:{item.value_sha256}" for item in environment)
    parent_pid = os.getppid()
    return TerminalProcess(
        pid=os.getpid(),
        parent_pid=parent_pid if parent_pid > 0 else None,
        command=command,
        command_sha256=hash_text(command),
        cwd=str(root),
        environment_sha256=hash_text(environment_fingerprint),
        started_at=now,
    )


def hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def hash_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def is_secret_name(name: str) -> bool:
    upper_name = name.upper()
    return any(fragment in upper_name for fragment in SECRET_NAME_FRAGMENTS)


def normalize_workspace_id(value: str) -> str:
    normalized = "".join(
        character if character.isalnum() or character in "_.:-" else "-" for character in value
    )
    return normalized[:128] or "workspace"


def api_get(url: str) -> object:
    validate_http_url(url)
    with urlopen(url, timeout=10) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def api_post_json(url: str, payload: str) -> object:
    validate_http_url(url)
    request = Request(  # noqa: S310
        url,
        data=payload.encode("utf-8"),
        headers={"content-type": "application/json"},
        method="POST",
    )
    with urlopen(request, timeout=30) as response:  # noqa: S310
        return json.loads(response.read().decode("utf-8"))


def validate_http_url(url: str) -> None:
    parsed_url = urlparse(url)
    if parsed_url.scheme not in {"http", "https"}:
        raise ValueError("api URL must use http or https")


def print_json(value: object) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
