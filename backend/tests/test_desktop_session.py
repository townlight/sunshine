"""The existing native session must not become ambient HTTP authentication."""

from __future__ import annotations

import hashlib
import hmac
import json
from pathlib import Path

import pytest

from townlight_records.auth.desktop_session import validate_native_session


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
    assert principal.allows_module("townlight_records")
    assert not principal.allows_module("townlight_access")
    assert not principal.allows_module("townlight_meetings")


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


@pytest.mark.asyncio
async def test_concurrent_native_identity_reconciliation_commits_once(db_session_factory, tmp_path):
    import asyncio
    import time
    from types import SimpleNamespace

    from sqlalchemy import func, select
    from townlight_runtime.native_accounts import accounts, provision_accounts

    from townlight_records.auth.desktop_session import NativeDesktopPrincipal, shared_staff_scope
    from townlight_records.auth.native_identity import mapped_native_actor
    from townlight_records.models.user import User

    config = tmp_path / "config"
    config.mkdir(parents=True, exist_ok=True)
    (config / "first-admin.json").write_text(json.dumps({
        "email": "admin@native-test.invalid",
        "display_name": "Admin",
        "role": "local-admin",
    }), encoding="utf-8")
    staff_path = config / "staff-users.json"
    staff_path.write_text("[]", encoding="utf-8")

    async with db_session_factory() as session:
        connection = await session.connection()
        await connection.run_sync(lambda conn: accounts.create(conn, checkfirst=True))
        await provision_accounts(session, tmp_path)
        await session.commit()

    clerk_email = "clerk@native-test.invalid"
    staff_path.write_text(json.dumps([{
        "email": clerk_email,
        "display_name": "Clerk",
        "role": "clerk",
        "active": True,
    }]), encoding="utf-8")

    async with db_session_factory() as session_one, db_session_factory() as session_two:
        clerk_query = select(User).where(func.lower(User.email) == clerk_email)
        assert await session_one.scalar(clerk_query) is None
        assert await session_two.scalar(clerk_query) is None

        principal = NativeDesktopPrincipal(
            email=clerk_email,
            display_name="Clerk",
            role="clerk",
            expires_at_unix_seconds=int(time.time()) + 300,
        )
        proof = "a" * 64

        async def identity_sync(session):
            await provision_accounts(session, tmp_path)

        request = SimpleNamespace(
            app=SimpleNamespace(state=SimpleNamespace(
                desktop_profile_root=tmp_path,
                desktop_domain_enabled=True,
                desktop_enabled_modules={"townlight_comms", "townlight_library"},
                desktop_identity_sync=identity_sync,
            )),
            state=SimpleNamespace(),
        )

        async def resolve_actor(session, module_id):
            actor = await mapped_native_actor(request, session, proof, module_id)
            return actor.id

        with shared_staff_scope(tmp_path, proof, principal):
            actor_ids = await asyncio.wait_for(asyncio.gather(
                resolve_actor(session_one, "townlight_comms"),
                resolve_actor(session_two, "townlight_library"),
            ), timeout=5)

        assert actor_ids[0] == actor_ids[1]
        await session_one.rollback()
        await session_two.rollback()

    async with db_session_factory() as session:
        users = (await session.scalars(
            select(User).where(func.lower(User.email) == clerk_email)
        )).all()
        assert len(users) == 1
        account_count = await session.scalar(
            select(func.count()).select_from(accounts).where(
                func.lower(accounts.c.email) == clerk_email
            )
        )
        assert account_count == 1
        account_user_id = await session.scalar(
            select(accounts.c.user_id).where(
                func.lower(accounts.c.email) == clerk_email
            )
        )
        assert account_user_id == actor_ids[0]
        assert users[0].id == actor_ids[0]

        with shared_staff_scope(tmp_path, proof, principal):
            retried = await mapped_native_actor(request, session, proof, "townlight_comms")
        assert retried.id == actor_ids[0]
