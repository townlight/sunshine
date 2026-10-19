"""The existing native session must not become ambient HTTP authentication."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from app.auth.desktop_session import validate_native_session


@pytest.fixture
def native_profile(tmp_path: Path) -> tuple[Path, str]:
    config = tmp_path / "config"
    config.mkdir()
    key = bytes(range(32))
    (tmp_path / "session-mac-secret.key").write_text(key.hex(), encoding="utf-8")
    account = {
        "display_name": "Synthetic Records Officer",
        "email": "records@example.invalid",
        "role": "records-staff",
        "active": True,
        "passcode_hash": "synthetic-credential-verifier",
    }
    (config / "first-admin.json").write_text(
        json.dumps({**account, "email": "admin@example.invalid", "role": "local-admin"}),
        encoding="utf-8",
    )
    (config / "staff-users.json").write_text(json.dumps([account]), encoding="utf-8")
    expiry = 2000
    message = f"{account['email']}\n{account['role']}\n{expiry}\n{account['passcode_hash']}"
    proof = hmac.new(key, message.encode(), hashlib.sha256).hexdigest()
    (config / "local-session.json").write_text(
        json.dumps({**account, "display_name": "Untrusted display text",
                    "expires_at_unix_seconds": expiry, "session_hash": proof}),
        encoding="utf-8",
    )
    return tmp_path, proof


def test_native_session_preserves_actor_and_module_capabilities(native_profile):
    root, proof = native_profile
    principal = validate_native_session(proof, profile_root=root, now_unix_seconds=1000)

    assert principal.email == "records@example.invalid"
    assert principal.display_name == "Synthetic Records Officer"
    assert principal.role == "records-staff"
    assert principal.expires_at_unix_seconds == 2000
    assert principal.allows_module("civicrecords-ai")
    assert not principal.allows_module("civicaccess")
    assert not principal.allows_module("civicclerk")


@pytest.mark.parametrize("proof", [None, "", "forged", "0" * 64])
def test_existing_on_disk_session_does_not_authenticate_an_unproven_caller(native_profile, proof):
    root, _ = native_profile
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=root, now_unix_seconds=1000)


def test_expired_native_session_is_denied(native_profile):
    root, proof = native_profile
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=root, now_unix_seconds=2000)


def test_sign_out_invalidates_previously_copied_proof(native_profile):
    root, proof = native_profile
    (root / "config" / "local-session.json").unlink()
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=root, now_unix_seconds=1000)


@pytest.mark.parametrize("change", [{"active": False}, {"role": "clerk"},
                                    {"passcode_hash": "replacement-verifier"}])
def test_current_account_changes_invalidate_native_proof(native_profile, change):
    root, proof = native_profile
    path = root / "config" / "staff-users.json"
    accounts = json.loads(path.read_text(encoding="utf-8"))
    accounts[0].update(change)
    path.write_text(json.dumps(accounts), encoding="utf-8")
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=root, now_unix_seconds=1000)


def test_session_file_role_edit_cannot_escalate_to_admin(native_profile):
    root, proof = native_profile
    path = root / "config" / "local-session.json"
    session = json.loads(path.read_text(encoding="utf-8"))
    session["role"] = "local-admin"
    path.write_text(json.dumps(session), encoding="utf-8")
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=root, now_unix_seconds=1000)


@pytest.mark.parametrize("filename,contents", [
    ("session-mac-secret.key", "not-a-key"),
    ("config/local-session.json", "not-json"),
    ("config/first-admin.json", "[]"),
    ("config/staff-users.json", "{}"),
])
def test_corrupt_native_state_fails_closed(native_profile, filename, contents):
    root, proof = native_profile
    (root / filename).write_text(contents, encoding="utf-8")
    with pytest.raises(PermissionError):
        validate_native_session(proof, profile_root=root, now_unix_seconds=1000)
