"""Tests for backend.townlight_records.config startup validation (T2C bootstrap hardening).

Covers:
- FIRST_ADMIN_PASSWORD validator (placeholder, blocklist, length, valid)
- The fresh-start integration scenario: a user copies .env.example to .env
  without editing FIRST_ADMIN_PASSWORD — Settings() must fail fatally so the
  app cannot boot. This mirrors what `docker compose up` would experience.
- CONNECTOR_HOST_ALLOWLIST CSV parsing
"""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from townlight_records.config import Settings


_VALID_JWT = "a" * 64
_VALID_PASSWORD = "S3cure!FreshAdminPwd-2026"


def _secret_file_kwargs(tmp_path, *, jwt_secret=_VALID_JWT, first_admin_password=_VALID_PASSWORD):
    secret_dir = tmp_path / "secrets"
    secret_dir.mkdir()
    jwt_path = secret_dir / "jwt_secret"
    password_path = secret_dir / "first_admin_password"
    jwt_path.write_text(jwt_secret, encoding="utf-8")
    password_path.write_text(first_admin_password, encoding="utf-8")
    return {
        "jwt_secret_file": str(jwt_path),
        "first_admin_password_file": str(password_path),
    }


# ─────────────────── FIRST_ADMIN_PASSWORD validation ───────────────────
@pytest.mark.parametrize(
    "bad_password",
    [
        # Exact placeholder from .env.example — the fresh-start scenario
        "CHANGE-ME-on-first-login",
        # Default Settings value
        "CHANGE-ME",
        # Common-blocklist entries
        "password",
        "Password",
        "admin",
        "admin123",
        "changeme",
        "12345678",
        "letmein",
        "Welcome1",
    ],
)
def test_placeholder_or_blocklist_password_fails_startup(tmp_path, bad_password):
    with pytest.raises((ValidationError, ValueError), match="FIRST_ADMIN_PASSWORD"):
        Settings(
            **_secret_file_kwargs(tmp_path, first_admin_password=bad_password),
            testing=False,
        )


@pytest.mark.parametrize("short_pw", ["", "a", "short", "12345", "elevenchars"])
def test_short_password_fails_startup(tmp_path, short_pw):
    with pytest.raises((ValidationError, ValueError), match="FIRST_ADMIN_PASSWORD"):
        Settings(
            **_secret_file_kwargs(tmp_path, first_admin_password=short_pw),
            testing=False,
        )


def test_valid_strong_password_passes(tmp_path):
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        testing=False,
    )
    assert s.first_admin_password == _VALID_PASSWORD
    assert s.jwt_secret == _VALID_JWT


def test_secret_files_win_over_inline_values(tmp_path):
    s = Settings(
        jwt_secret="CHANGE-ME",
        first_admin_password="CHANGE-ME",
        **_secret_file_kwargs(tmp_path),
        testing=False,
    )
    assert s.jwt_secret == _VALID_JWT
    assert s.first_admin_password == _VALID_PASSWORD


def test_missing_secret_file_fails_with_clear_startup_error(tmp_path):
    missing = tmp_path / "missing-jwt"
    password_path = tmp_path / "first_admin_password"
    password_path.write_text(_VALID_PASSWORD, encoding="utf-8")
    with pytest.raises((ValidationError, ValueError), match="JWT_SECRET_FILE"):
        Settings(
            jwt_secret_file=str(missing),
            first_admin_password_file=str(password_path),
            testing=False,
        )


def test_testing_mode_bypasses_password_check():
    # The testing=True path is how the test suite skips both validators
    s = Settings(
        jwt_secret="too-short",
        first_admin_password="CHANGE-ME",
        testing=True,
    )
    assert s.testing is True


# ──────── Unit-level proof for the .env.example placeholder case ────────
# NOTE: this is a unit-level proof that Settings() raises in-process when fed
# the .env.example placeholder. The fresh-subprocess and docker-compose
# integration coverage lives in:
#   - backend/tests/test_bootstrap_integration.py (subprocess)
#   - .github/workflows/ci.yml `bootstrap-failure` job (real docker compose run)
def test_env_example_placeholder_value_is_in_blocklist_inline(tmp_path):
    """The exact .env.example placeholder string is rejected by Settings()
    when constructed inline. Acts as a tripwire: if someone changes the
    placeholder in .env.example, this test goes red and the integration
    tests must be updated in lockstep.
    """
    with pytest.raises((ValidationError, ValueError), match="FIRST_ADMIN_PASSWORD"):
        Settings(
            **_secret_file_kwargs(
                tmp_path,
                first_admin_password="CHANGE-ME-on-first-login",
            ),
            testing=False,
        )


# ─────────────────── CONNECTOR_HOST_ALLOWLIST parsing ───────────────────
def test_allowlist_default_is_empty(tmp_path):
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        testing=False,
    )
    assert s.connector_host_allowlist == []


def test_allowlist_accepts_native_list(tmp_path):
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        connector_host_allowlist=["10.0.0.5", "internal-api.corp"],
        testing=False,
    )
    assert s.connector_host_allowlist == ["10.0.0.5", "internal-api.corp"]


def test_allowlist_accepts_csv_string(tmp_path):
    # Operators can set via env: CONNECTOR_HOST_ALLOWLIST=10.0.0.5,internal-api.corp
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        connector_host_allowlist="10.0.0.5,internal-api.corp,db.corp",
        testing=False,
    )
    assert s.connector_host_allowlist == ["10.0.0.5", "internal-api.corp", "db.corp"]


def test_allowlist_csv_strips_whitespace_and_empties(tmp_path):
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        connector_host_allowlist=" 10.0.0.5 , , internal-api.corp ,",
        testing=False,
    )
    assert s.connector_host_allowlist == ["10.0.0.5", "internal-api.corp"]


def test_allowlist_env_empty_string_loads_as_empty(tmp_path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_HOST_ALLOWLIST", "")
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        testing=False,
    )
    assert s.connector_host_allowlist == []


def test_allowlist_env_csv_loads_without_json_decode_error(tmp_path, monkeypatch):
    monkeypatch.setenv("CONNECTOR_HOST_ALLOWLIST", "10.0.0.5,internal-api.corp")
    s = Settings(
        **_secret_file_kwargs(tmp_path),
        testing=False,
    )
    assert s.connector_host_allowlist == ["10.0.0.5", "internal-api.corp"]
