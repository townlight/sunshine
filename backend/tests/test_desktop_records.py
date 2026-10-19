"""P2: real native-boundary intake/readback/actor, with no real profile data."""

import hashlib
import hmac
import json
import uuid

from httpx import ASGITransport, AsyncClient
import pytest
from sqlalchemy import func, select

from app.database import get_async_session
from app.main import create_app
from app.models.audit import AuditLog
from app.models.notifications import NotificationLog
from app.models.request import RecordsRequest
from app.models.request_workflow import RequestTimeline
from app.models.user import User, UserRole
from tests.conftest import override_get_session, test_session_maker as session_factory
from tests.test_desktop_session import native_profile as native_profile # noqa: F401 — shared synthetic fixture


INTAKE = {"requester": "Synthetic Resident", "summary": "Trail maintenance records",
          "deadline": "2026-10-15", "deadlineBasis": "Synthetic staff-reviewed basis"}


@pytest.fixture
async def native_api(client, native_profile, monkeypatch):
    root, proof = native_profile
    monkeypatch.setattr("app.auth.desktop_session.time.time", lambda: 1000)
    monkeypatch.setattr("app.audit.middleware.async_session_maker", session_factory)
    actor_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(User(id=actor_id, email="records@example.invalid", hashed_password="!native-only",
                         full_name="Synthetic Records Officer", role=UserRole.STAFF,
                         is_active=True, is_superuser=False, is_verified=True,
                         must_change_password=False))
        await session.commit()
    app = create_app(desktop_profile_root=root,
                     desktop_domain_enabled=True,
                     desktop_enabled_modules=frozenset({"civicrecords-ai", "civicaccess"}))
    app.dependency_overrides[get_async_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as api:
        yield api, proof, actor_id, app


@pytest.mark.asyncio
async def test_native_intake_persists_mapping_readback_and_real_actor(native_api):
    api, proof, actor_id, app = native_api
    headers = {"X-Townlight-Session": proof}
    response = await api.post("/desktop/v1/requests", json=INTAKE, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["requester_name"] == INTAKE["requester"]
    assert body["description"] == INTAKE["summary"]
    assert body["created_by"] == str(actor_id)
    assert body["assigned_to"] is None  # native intake is NOT web creator-assignment
    assert body.get("public_tracking_number") == "REQ-0001"
    assert body.get("deadline_basis") == INTAKE["deadlineBasis"]
    assert body.get("submitted_via") == "Staff intake"
    assert body.get("deadline_reviewed_at") is not None

    readback = await api.get(f"/desktop/v1/requests/{body['id']}", headers=headers)
    assert readback.status_code == 200
    assert readback.json() == body
    # Recreate the application boundary; a process restart is a later runtime
    # check, not something this ASGI reconstruction claims to prove.
    recreated = create_app(desktop_profile_root=app.state.desktop_profile_root,
                           desktop_domain_enabled=True,
                           desktop_enabled_modules=app.state.desktop_enabled_modules)
    recreated.dependency_overrides[get_async_session] = override_get_session
    async with AsyncClient(transport=ASGITransport(app=recreated), base_url="http://test") as restarted:
        after = await restarted.get(f"/desktop/v1/requests/{body['id']}", headers=headers)
        assert after.json() == body
    async with session_factory() as session:
        entry = (await session.execute(select(AuditLog).where(
            AuditLog.action == "create-records-request"
        ))).scalar_one()
        assert entry.user_id == actor_id
        assert entry.resource_id == body["id"]
        assert entry.details["native_role"] == "records-staff"
        assert await session.scalar(select(func.count()).select_from(RequestTimeline)) == 1
        outbox = (await session.execute(select(NotificationLog))).scalar_one()
        assert outbox.status == "ready to send"
        assert outbox.channel == "local notification outbox"
        assert outbox.request_id == uuid.UUID(body["id"])


@pytest.mark.asyncio
async def test_native_calls_require_explicit_proof_and_reject_payload_actor(native_api):
    api, proof, _, _ = native_api
    denied = await api.post("/desktop/v1/requests", json=INTAKE)
    assert denied.status_code == 401
    forged = await api.post("/desktop/v1/requests", json=INTAKE,
                            headers={"X-Townlight-Session": "0" * 64})
    assert forged.status_code == 401
    injected = await api.post("/desktop/v1/requests", json={**INTAKE, "actor": "admin"},
                              headers={"X-Townlight-Session": proof})
    assert injected.status_code == 422
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 0


@pytest.mark.asyncio
async def test_native_state_refresh_uses_canonical_ids_and_current_approval(native_api):
    api, proof, actor_id, app = native_api
    headers = {"X-Townlight-Session": proof}
    assert (await api.get("/desktop/v1/records-state")).status_code == 401
    empty = await api.get("/desktop/v1/records-state", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["records_requests"] == []
    assert empty.json()["notification_events"] == []
    assert empty.json()["publication_events"] == []
    created = await api.post("/desktop/v1/requests", json=INTAKE, headers=headers)
    request_id = created.json()["id"]
    for action, payload in [
        ("draft-records-response", {"responseDraft": "First response", "citation": "Synthetic meeting record"}),
        ("approve-records-response", {"approvalNote": "Reviewed first response"}),
        ("draft-records-response", {"responseDraft": "Revised response"}),
    ]:
        result = await api.post(f"/desktop/v1/requests/{request_id}/actions",
                                json={"action": action, "payload": payload}, headers=headers)
        assert result.status_code == 200, result.text
    state = await api.get("/desktop/v1/records-state", headers=headers)
    assert state.status_code == 200, state.text
    rows = state.json()["records_requests"]
    assert len(rows) == 1
    assert rows[0]["request_id"] == request_id
    assert rows[0]["id"] == created.json()["desktop_id"]
    assert rows[0]["response_draft"] == "Revised response"
    assert rows[0]["approved_at_unix_seconds"] is None
    assert "Reviewed first response" in rows[0]["approval_notes"]
    individual = await api.get(f"/desktop/v1/requests/{request_id}/view", headers=headers)
    assert individual.json() == rows[0]
    app.state.desktop_domain_enabled = False
    assert (await api.get("/desktop/v1/records-state", headers=headers)).status_code == 503


@pytest.mark.asyncio
@pytest.mark.parametrize("change", [{"is_active": False}, {"must_change_password": True},
                                    {"role": UserRole.ADMIN}])
async def test_native_identity_mapping_fails_closed_without_promotion(native_api, change):
    api, proof, actor_id, _ = native_api
    async with session_factory() as session:
        actor = await session.get(User, actor_id)
        for key, value in change.items():
            setattr(actor, key, value)
        await session.commit()
    response = await api.post("/desktop/v1/requests", json=INTAKE,
                              headers={"X-Townlight-Session": proof})
    assert response.status_code == 403
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 0


@pytest.mark.asyncio
async def test_native_role_and_enabled_profile_are_both_required(native_api):
    api, proof, _, app = native_api
    app.state.desktop_enabled_modules = frozenset({"civicaccess"})
    response = await api.post("/desktop/v1/requests", json=INTAKE,
                              headers={"X-Townlight-Session": proof})
    assert response.status_code == 403
    app.state.desktop_enabled_modules = frozenset({"civicrecords-ai"})
    app.state.desktop_domain_enabled = False
    inactive = await api.post("/desktop/v1/requests", json=INTAKE,
                             headers={"X-Townlight-Session": proof})
    assert inactive.status_code == 503
    app.state.desktop_domain_enabled = True
    root = app.state.desktop_profile_root
    accounts_path = root / "config" / "staff-users.json"
    accounts = json.loads(accounts_path.read_text())
    accounts[0]["role"] = "clerk"
    accounts_path.write_text(json.dumps(accounts))
    session_path = root / "config" / "local-session.json"
    saved = json.loads(session_path.read_text())
    saved["role"] = "clerk"
    message = f"{saved['email']}\nclerk\n{saved['expires_at_unix_seconds']}\n{accounts[0]['passcode_hash']}"
    saved["session_hash"] = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    session_path.write_text(json.dumps(saved))
    response = await api.post("/desktop/v1/requests", json=INTAKE,
                              headers={"X-Townlight-Session": saved["session_hash"]})
    assert response.status_code == 403


@pytest.mark.asyncio
async def test_ordinary_web_app_does_not_mount_native_routes(client):
    response = await client.post("/desktop/v1/requests", json=INTAKE)
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_shared_intake_failure_leaves_no_partial_request(native_api, monkeypatch):
    from app.requests import service

    _, _, actor_id, _ = native_api

    async def audit_unavailable(**kwargs):
        raise RuntimeError("synthetic audit failure")

    monkeypatch.setattr(service, "write_audit_log", audit_unavailable)
    async with session_factory() as session:
        actor = await session.get(User, actor_id)
        with pytest.raises(RuntimeError, match="synthetic audit failure"):
            await service.create_records_request(
                session, service.RequestIntake("Synthetic Resident", "Aborted intake"),
                actor=actor, assigned_to=None, department_id=None,
            )
        await session.rollback()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 0


def isolated_runtime_app():
    """Uvicorn factory for this test's disposable profile, never a shipping mode."""
    import os
    if os.environ.get("TESTING") != "1":
        raise RuntimeError("The isolated runtime factory is test-only.")
    from civicsuite_runtime.services import create_runtime_app
    return create_runtime_app(domain_enabled=True)


@pytest.mark.asyncio
async def test_real_loopback_runtime_write_survives_process_restart(client, native_profile, tmp_path):
    """P2 process proof, distinct from ASGI reconstruction and installed proof."""
    import asyncio
    import os
    from pathlib import Path
    import socket
    import subprocess
    import sys
    import time
    import httpx
    from tests.conftest import TEST_DATABASE_URL
    from app.audit.logger import verify_chain

    runtime_root = Path(__file__).resolve().parents[3] / "townlight/desktop/runtime/python-services"
    if not runtime_root.is_dir():
        pytest.skip("This cross-repository runtime proof requires the paired Townlight checkout.")
    from civicaccess.access_review import AccessibilityReviewRepository
    sys.path.insert(0, str(runtime_root))
    from civicsuite_runtime.access_bridge import ensure_native_schema
    repository = AccessibilityReviewRepository(db_url=TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    try:
        ensure_native_schema(repository.engine)
        from civicsuite_runtime.records_import_store import ensure_schema
        from civicsuite_runtime.native_accounts import metadata
        ensure_schema(repository.engine)
        metadata.create_all(repository.engine)
    finally:
        repository.engine.dispose()
    root, _ = native_profile
    session_file = root / "config/local-session.json"
    saved = json.loads(session_file.read_text())
    saved["expires_at_unix_seconds"] = int(time.time()) + 3600
    message = f"{saved['email']}\n{saved['role']}\n{saved['expires_at_unix_seconds']}\nsynthetic-credential-verifier"
    proof = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    saved["session_hash"] = proof
    session_file.write_text(json.dumps(saved))
    actor_id = uuid.uuid4()
    async with session_factory() as session:
        session.add(User(id=actor_id, email=saved["email"], hashed_password="!native-only",
                         full_name="Synthetic Records Officer", role=UserRole.STAFF,
                         is_active=True, is_superuser=False, is_verified=True,
                         must_change_password=False))
        await session.commit()
    with socket.socket() as reservation:
        native_transport = os.environ.get("TOWNLIGHT_TEST_NATIVE_TRANSPORT") == "1"
        reservation.bind(("127.0.0.1", 15480 if native_transport else 0))
        port = reservation.getsockname()[1]
    env = {**os.environ, "TESTING": "1", "DATABASE_URL": TEST_DATABASE_URL,
           "CIVICSUITE_DATA_DIR": str(root / "data"), "TOWNLIGHT_PRODUCT_PROFILE": "records-beta",
           "PYTHONPATH": str(runtime_root) + os.pathsep + os.environ.get("PYTHONPATH", "")}
    command = [sys.executable, "-m", "uvicorn", "tests.test_desktop_records:isolated_runtime_app",
               "--factory", "--host", "127.0.0.1", "--port", str(port),
               "--no-access-log", "--log-level", "warning"]
    headers = {"X-Townlight-Session": proof}
    created = None
    for launch in (1, 2):
        with (tmp_path / f"domain-runtime-{launch}.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(command, cwd=Path(__file__).resolve().parents[1], env=env,
                                       stdout=log, stderr=subprocess.STDOUT,
                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            try:
                async with httpx.AsyncClient(base_url=f"http://127.0.0.1:{port}", timeout=3) as api:
                    deadline = time.monotonic() + 15
                    while True:
                        assert process.poll() is None, f"Runtime exited; inspect domain-runtime-{launch}.log"
                        try:
                            ready = await api.get("/ready")
                            if ready.status_code == 200:
                                break
                        except httpx.ConnectError:
                            pass
                        assert time.monotonic() < deadline, "Domain runtime did not become ready."
                        await asyncio.sleep(0.1)
                    health = await api.get("/health")
                    assert health.status_code == 200, health.text
                    if launch == 1:
                        denied = await api.post("/desktop/v1/requests", json=INTAKE)
                        assert denied.status_code == 401
                        response = await api.post("/desktop/v1/requests", json=INTAKE, headers=headers)
                        assert response.status_code == 201, response.text
                        created = response.json()
                        if native_transport:
                            source = tmp_path / "native-source.txt"
                            source.write_bytes(b"Synthetic source bytes")
                            native_env = {**env, "TOWNLIGHT_TEST_SESSION_PROOF": proof,
                                          "CIVICSUITE_DESKTOP_STATE_DIR": str(root),
                                          "TOWNLIGHT_TEST_SOURCE_FILE": str(source)}
                            desktop = runtime_root.parents[1]
                            native_command = ["cargo", "test", "--offline", "--manifest-path", "src-tauri/Cargo.toml",
                                              "-j", "2", "native_records_roundtrip_with_real_runtime", "--", "--ignored", "--nocapture"]
                            # The runtime is a separate process; blocking here does not block its HTTP loop.
                            completed = subprocess.run(native_command, cwd=desktop, env=native_env,
                                                       capture_output=True, text=True, timeout=180,
                                                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
                            assert completed.returncode == 0, completed.stdout + completed.stderr
                    else:
                        response = await api.get(f"/desktop/v1/requests/{created['id']}", headers=headers)
                        assert response.status_code == 200
                        assert response.json() == created
            finally:
                process.terminate()
                process.wait(timeout=10)
    async with session_factory() as session:
        entry = (await session.execute(select(AuditLog).where(
            AuditLog.action == "create-records-request", AuditLog.resource_id == created["id"]
        ))).scalar_one()
        assert entry.user_id == actor_id
        valid, _, error = await verify_chain(session)
        assert valid, error
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == (2 if native_transport else 1)
    assert not (root / "data/workflows/city-work.json").exists()
