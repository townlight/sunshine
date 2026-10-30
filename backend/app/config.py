from pathlib import Path
from typing import Annotated, Literal

from civiccore.security import (
    DEFAULT_INSECURE_FERNET_KEY_VALUES,
    DEFAULT_INSECURE_PASSWORD_VALUES,
    DEFAULT_INSECURE_SECRET_VALUES,
    parse_csv_setting,
    validate_fernet_key_setting,
    validate_password_setting,
    validate_secret_setting,
)
from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode

APP_VERSION = "1.8.0.dev1"

_INSECURE_SECRETS = DEFAULT_INSECURE_SECRET_VALUES
_INSECURE_ENCRYPTION_KEYS = DEFAULT_INSECURE_FERNET_KEY_VALUES
_INSECURE_PASSWORDS = DEFAULT_INSECURE_PASSWORD_VALUES
_MIN_PASSWORD_LEN = 12


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://civicrecords:civicrecords@postgres:5432/civicrecords"
    jwt_secret: str = "CHANGE-ME"
    # Default to the Docker Compose secret mount path. Pydantic-settings will
    # only override from env if a JWT_SECRET_FILE env var is set; the
    # B2 contract is that the container env contains no such name, so this
    # default IS the production read path.
    jwt_secret_file: str = "/run/secrets/jwt_secret"
    jwt_lifetime_seconds: int = 3600
    first_admin_email: str = "admin@example.gov"
    first_admin_password: str = "CHANGE-ME"
    first_admin_password_file: str = "/run/secrets/first_admin_password"
    ollama_base_url: str = "http://ollama:11434"
    redis_url: str = "redis://redis:6379/0"
    audit_retention_days: int = 1095
    cors_origins: list[str] = ["http://localhost:8080"]
    embedding_model: str = "nomic-embed-text"
    # T5C: gemma4:e4b is the single truthful default across runtime-config surfaces,
    # matching installer picker default. Tier 5 Blocker 1 resolution 2026-04-21.
    chat_model: str = "gemma4:e4b"
    vision_model: str = "gemma4:e4b"
    # SMTP settings for notification email delivery.
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    smtp_from_email: str = "noreply@civicrecords.local"
    smtp_use_tls: bool = True

    # Empty by default. No wildcard support, no "disable all" escape hatch.
    connector_host_allowlist: Annotated[list[str], NoDecode] = []

    # "private" keeps staff-only posture. "public" exposes the minimal resident portal.
    portal_mode: Literal["public", "private"] = "private"

    # Fernet-compatible key for data_sources.connection_config encrypted JSON envelopes.
    encryption_key: str = "CHANGE-ME-generate-with-fernet-generate-key"

    testing: bool = False

    # Deployment/tenant scope for CivicCore department authority (see
    # civiccore.auth.department_scope). Configured server-side by the operator;
    # Records never derives it from a request. Empty = deny all staff reads that
    # require department authority (fail closed, no permissive fallback).
    authority_scope_id: str = ""

    model_config = {"env_file": ".env", "extra": "ignore"}

    @staticmethod
    def _read_required_secret_file(path_value: str, *, setting_name: str) -> str:
        if not path_value:
            raise ValueError(
                f"{setting_name}_FILE must point to a mounted secret file. "
                f"Re-run install.sh/install.ps1 or create a 0400 secret file and set {setting_name}_FILE."
            )
        path = Path(path_value)
        try:
            value = path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise ValueError(
                f"{setting_name}_FILE points to an unreadable secret file: {path}"
            ) from exc
        if not value:
            raise ValueError(f"{setting_name}_FILE points to an empty secret file: {path}")
        return value

    @model_validator(mode="after")
    def load_secret_files(self):
        if self.testing:
            return self
        self.jwt_secret = self._read_required_secret_file(
            self.jwt_secret_file,
            setting_name="JWT_SECRET",
        )
        self.first_admin_password = self._read_required_secret_file(
            self.first_admin_password_file,
            setting_name="FIRST_ADMIN_PASSWORD",
        )
        return self

    @model_validator(mode="after")
    def check_jwt_secret(self):
        if self.testing:
            return self
        validate_secret_setting(self.jwt_secret, setting_name="JWT_SECRET")
        return self

    @field_validator("connector_host_allowlist", mode="before")
    @classmethod
    def _parse_allowlist_csv(cls, v):
        # Accept CSV strings from env in addition to native lists.
        return parse_csv_setting(v) if isinstance(v, (str, list, tuple, set)) or v is None else v

    @field_validator("authority_scope_id", mode="before")
    @classmethod
    def _normalize_authority_scope(cls, v):
        """Normalize the configured scope id; malformed values are refused later."""
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @field_validator("portal_mode", mode="before")
    @classmethod
    def _normalize_portal_mode(cls, v):
        if isinstance(v, str):
            return v.strip().lower()
        return v

    @model_validator(mode="after")
    def check_encryption_key(self):
        if self.testing:
            return self
        validate_fernet_key_setting(self.encryption_key, setting_name="ENCRYPTION_KEY")
        return self

    @model_validator(mode="after")
    def check_first_admin_password(self):
        if self.testing:
            return self
        validate_password_setting(
            self.first_admin_password,
            setting_name="FIRST_ADMIN_PASSWORD",
            min_length=_MIN_PASSWORD_LEN,
        )
        return self


settings = Settings()
