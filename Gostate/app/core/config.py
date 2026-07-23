"""Application configuration boundaries."""

from __future__ import annotations

import os
from enum import StrEnum
from typing import Annotated, Final

from pydantic import BaseModel, ConfigDict, Field, model_validator

SUPABASE_DATABASE_URL_ENV: Final[str] = "SUPABASE_DATABASE_URL"
STORAGE_BACKEND_ENV: Final[str] = "GOSTATE_STORAGE_BACKEND"
DEV_MODE_ENV: Final[str] = "GOSTATE_DEV_MODE"

DatabaseUrl = Annotated[str, Field(min_length=1)]


class StorageBackend(StrEnum):
    MEMORY = "memory"
    SUPABASE = "supabase"


class AppSettings(BaseModel):
    """Runtime settings with explicit storage backend selection."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    storage_backend: StorageBackend
    supabase_database_url: DatabaseUrl | None = None
    dev_mode: bool = False

    @model_validator(mode="after")
    def validate_backend_contract(self) -> AppSettings:
        if self.storage_backend is StorageBackend.SUPABASE and self.supabase_database_url is None:
            raise RuntimeError(f"{SUPABASE_DATABASE_URL_ENV} is required for Supabase storage")
        return self


def load_app_settings() -> AppSettings:
    raw_backend = os.getenv(STORAGE_BACKEND_ENV, StorageBackend.MEMORY.value)
    return AppSettings(
        storage_backend=StorageBackend(raw_backend),
        supabase_database_url=os.getenv(SUPABASE_DATABASE_URL_ENV),
        dev_mode=os.getenv(DEV_MODE_ENV, "false").lower() in {"1", "true", "yes"},
    )
