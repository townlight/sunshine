"""Real PostgreSQL import: lossless projection, idempotency and atomic rejection."""
import copy
import hashlib
import hmac
import json
import uuid

import pytest
pytest.importorskip("civicsuite_runtime", reason="Requires paired Townlight runtime")
from sqlalchemy import select, func
from civicaccess.access_review import AccessibilityReviewRepository
from civicsuite_runtime.access_bridge import ensure_native_schema, state as access_state
from civicsuite_runtime.records_import import preflight
from civicsuite_runtime.records_import_store import ensure_schema, import_snapshot, imports, legacy_audit
from app.desktop_bridge.projection import request_view
from app.models.request import RecordsRequest
from tests.conftest import TEST_DATABASE_URL, test_session_maker as session_factory
from tests.test_desktop_records import native_api, native_profile  # noqa: F401
from tests.test_records_import_preflight import sample, source


def storage_schema():
    repository = AccessibilityReviewRepository(db_url=TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    try:
        ensure_native_schema(repository.engine)
        ensure_schema(repository.engine)
        from civicsuite_runtime.native_accounts import metadata
        metadata.create_all(repository.engine)
    finally:
        repository.engine.dispose()


def full_sample(root):
    data = sample()
    row = data["records_requests"][0]
    row.update(public_tracking_number="REQ-0001", assigned_to="Historical officer",
        clarification_notes=["Scope agreed"], search_notes=["Archive searched"], citations=["Archive 1"],
        exemption_reviews=["Human-reviewed"], fee_estimate="$1.25", fee_waiver_reason="Historical reason",
        timeline=[dict(id="tl-1", action="approved", actor="Historical approver", note="Approved text", created_at_unix_seconds=1001)],
        messages=[dict(id="m-1", author="Historical resident", author_role="requester", body="Scope", visibility="requester thread", created_at_unix_seconds=1000)],
        public_status_events=[dict(id="ps-1", label="Received", summary="Under review", status="received", created_at_unix_seconds=1000)],
        exemption_decisions=[dict(id="ed-1", source="Page 1", kind="privacy", finding="Review", decision="redact", basis="Human basis", reviewer="Historical reviewer", created_at_unix_seconds=1000)],
        fee_line_items=[dict(id="fee-1", description="Copy", schedule_basis="Historical schedule", amount_cents=125, created_at_unix_seconds=1000)],
        search_sessions=[dict(id="search-1", query="Trail", locations="Archive", reviewer="Historical searcher", created_at_unix_seconds=1000,
            results=[dict(id="hit-1", title="Minutes", citation="M1", summary="Trail work", status="Reviewed")])])
    folder = root / "Data" / "files" / "records"
    folder.mkdir(parents=True)
    original = folder / "original.txt"
    original.write_bytes(b"SYNTHETIC source")
    row["documents"] = [dict(id="doc-1", title="Source", original_path="historical path",
        stored_path=str(original), citation="Source 1", sha256=hashlib.sha256(original.read_bytes()).hexdigest(),
        size_bytes=original.stat().st_size, status="attached for response review", added_by="Historical officer", created_at_unix_seconds=1000)]
    release = folder / "release.txt"
    release.write_bytes(b"SYNTHETIC reviewed release")
    row["documents"][0].update(status="release-ready copy attached", release_original_path="historical reviewed copy",
        release_stored_path=str(release), release_file_name=release.name,
        release_sha256=hashlib.sha256(release.read_bytes()).hexdigest(), release_size_bytes=release.stat().st_size,
        release_status="release-ready copy", release_note="Historical decision", release_added_by="Historical reviewer", release_added_at_unix_seconds=1001)
    row["release_packages"] = []
    for index in range(2):
        artifact = folder / f"package-{index}.md"
        artifact.write_bytes(f"SYNTHETIC historical package {index}".encode())
        digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
        artifact.with_name(artifact.name + ".manifest.json").write_text(json.dumps(dict(schema_version=1,
            export_file=artifact.name, sha256=digest, size_bytes=artifact.stat().st_size)))
        row["release_packages"].append(dict(id=f"package-{index}", export_path=str(artifact), package_hash=digest,
            document_count=1, release_artifact_count=1, search_session_count=1, release_count=1, redacted_count=0,
            exempt_count=0, created_at_unix_seconds=1001))
    data["access"] = {"reviews":[dict(review_id="review-1", title="Historical notice", body="Review me",
        has_alt_text=False, language="en", status="needs-review", findings=[], disclaimer="Advisory",
        ai_analysis="Historical advisory", ai_analysis_model="historical-model", created_at_unix_seconds=1000)],
        "audit_events":[dict(event_id="access-event-1", action="review.create", subject_id="review-1", actor="historical actor", created_at_unix_seconds=1000)]}
    data["demo_fixture"] = {"fixture_id":"synthetic-test", "watermark":"SYNTHETIC"}
    return data


@pytest.mark.asyncio
async def test_import_is_lossless_idempotent_and_refuses_changed_source(native_api):
    _, _, actor_id, app = native_api
    root = app.state.desktop_profile_root
    storage_schema()
    data = full_sample(root)
    path = source(root, data)
    before = path.read_bytes()
    backup = root / "preserved-city-work.json"
    backup.write_bytes(before)
    snapshot = preflight(root)
    async with session_factory() as session:
        receipt = await import_snapshot(session, root, snapshot.source_sha256, backup, actor_id)
    async with session_factory() as session:
        repeat = await import_snapshot(session, root, snapshot.source_sha256, backup, actor_id)
    assert receipt == repeat
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 1
        req = await session.get(RecordsRequest, uuid.UUID(snapshot.records[0].request_id))
        assert await request_view(session, req) == snapshot.records[0]
        assert req.created_by is None  # No invented historical actor.
        assert req.approved_response_sha256 == hashlib.sha256(req.response_draft.encode()).hexdigest()
        audit = (await session.execute(select(legacy_audit))).mappings().one()
        assert audit["entry_hash"] == data["audit_entries"][0]["entry_hash"]
        access = await access_state(session)
        assert access["reviews"][0]["review_id"] == "review-1"
        assert access["reviews"][0]["ai_analysis"] == "Historical advisory"
        assert access["audit_events"] == data["access"]["audit_events"]
    data["records_requests"][0]["summary"] = "Changed legacy bytes"
    source(root, data)
    changed = preflight(root)
    changed_backup = root / "different-backup.json"
    changed_backup.write_bytes(path.read_bytes())
    async with session_factory() as session:
        with pytest.raises(ValueError, match="different legacy source"):
            await import_snapshot(session, root, changed.source_sha256, changed_backup, actor_id)
    assert backup.read_bytes() == before


@pytest.mark.asyncio
async def test_import_failure_rolls_back_rows_and_completion_receipt(native_api):
    _, _, actor_id, app = native_api
    root = app.state.desktop_profile_root
    storage_schema()
    data = sample()
    invalid = copy.deepcopy(data["records_requests"][0])
    invalid.update(id="second", status="unsupported-state")
    data["records_requests"].append(invalid)
    path = source(root, data)
    before = path.read_bytes()
    backup = root / "preserved-city-work.json"
    backup.write_bytes(before)
    snapshot = preflight(root)
    async with session_factory() as session:
        with pytest.raises(ValueError, match="Unsupported legacy Records status"):
            await import_snapshot(session, root, snapshot.source_sha256, backup, actor_id)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 0
        assert await session.scalar(select(func.count()).select_from(imports)) == 0
    assert path.read_bytes() == backup.read_bytes() == before


@pytest.mark.asyncio
async def test_identity_mapping_does_not_repurpose_existing_users(client, native_profile):
    from civicsuite_runtime.native_accounts import provision_accounts, accounts
    from app.models.user import User, UserRole
    root, _ = native_profile
    storage_schema()
    async with session_factory() as session:
        async with session.begin():
            mapping = await provision_accounts(session, root)
    async with session_factory() as session:
        admin = await session.get(User, mapping["admin@example.invalid"])
        staff = await session.get(User, mapping["records@example.invalid"])
        assert admin.role == UserRole.ADMIN
        assert staff.role == UserRole.STAFF
        assert not staff.is_superuser
        assert staff.hashed_password != "synthetic-credential-verifier"
    async with session_factory() as session:
        async with session.begin():
            assert await provision_accounts(session, root) == mapping
    # A different pre-existing account is not silently elevated or claimed.
    admin_path = root / "config" / "first-admin.json"
    admin_data = json.loads(admin_path.read_bytes())
    admin_data["email"] = "seed-admin@test.internal"
    admin_path.write_text(json.dumps(admin_data))
    async with session_factory() as session:
        with pytest.raises(ValueError, match="collides"):
            async with session.begin():
                await provision_accounts(session, root)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(accounts)) == 2


@pytest.mark.asyncio
async def test_cutover_recovers_committed_import_without_json_fallback(client, native_profile, monkeypatch):
    from civicsuite_runtime import records_cutover
    root, staff_proof = native_profile
    monkeypatch.setattr("app.auth.desktop_session.time.time", lambda: 1000)
    storage_schema()
    data = full_sample(root)
    path = source(root, data)
    snapshot = preflight(root)
    backup = root / "before-cutover.json"
    backup.write_bytes(path.read_bytes())
    journal = root / "config" / "records-authority.json"
    journal.write_text(json.dumps(dict(schema_version=1, phase="importing",
        source_sha256=snapshot.source_sha256, backup_path=str(backup))))
    with pytest.raises(PermissionError):
        await records_cutover.cutover(root, TEST_DATABASE_URL, staff_proof)
    admin = json.loads((root / "config" / "first-admin.json").read_bytes())
    key = bytes.fromhex((root / "session-mac-secret.key").read_text())
    proof = hmac.new(key, f"{admin['email']}\nlocal-admin\n2000\n{admin['passcode_hash']}".encode(), hashlib.sha256).hexdigest()
    (root / "config" / "local-session.json").write_text(json.dumps({**admin, "expires_at_unix_seconds":2000, "session_hash":proof}))
    replace = records_cutover.os.replace
    def interrupted(*args):
        raise OSError("Synthetic interruption after commit")
    monkeypatch.setattr(records_cutover.os, "replace", interrupted)
    with pytest.raises(OSError, match="Synthetic interruption"):
        await records_cutover.cutover(root, TEST_DATABASE_URL, proof)
    assert not records_cutover.verify_activation(root, TEST_DATABASE_URL)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 1
    monkeypatch.setattr(records_cutover.os, "replace", replace)
    await records_cutover.cutover(root, TEST_DATABASE_URL, proof)
    assert records_cutover.verify_activation(root, TEST_DATABASE_URL)
    assert path.read_bytes() == backup.read_bytes()
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 1
        from civicsuite_runtime.records_snapshot import snapshot as suite_snapshot
        from civicsuite_runtime.native_accounts import accounts
        admin_id = await session.scalar(select(accounts.c.user_id).where(accounts.c.email == admin["email"]))
        view = await suite_snapshot(session, ["civicrecords-ai", "civicaccess"], admin_id)
        assert view["demo_fixture"] == data["demo_fixture"]
        assert view["audit_entries"][0]["entry_hash"] == data["audit_entries"][0]["entry_hash"]


@pytest.mark.asyncio
async def test_canonical_demo_is_idempotent_and_exports_its_watermark(native_api):
    from civicsuite_runtime.records_demo import load_demo, FIXTURE_HASH
    from tests.test_desktop_records_lifecycle import operation
    _, proof, actor_id, app = native_api
    api = native_api[0]
    root = app.state.desktop_profile_root
    storage_schema()
    data = sample()
    data["records_requests"] = []
    data["audit_entries"] = []
    path = source(root, data)
    backup = root / "pre-import.json"
    backup.write_bytes(path.read_bytes())
    first = preflight(root)
    async with session_factory() as session:
        await import_snapshot(session, root, first.source_sha256, backup, actor_id)
    async with session_factory() as session:
        async with session.begin():
            marker = await load_demo(session, root, actor_id)
    async with session_factory() as session:
        async with session.begin():
            assert await load_demo(session, root, actor_id) == marker
        req_id = await session.scalar(select(RecordsRequest.id))
        assert await session.scalar(select(func.count()).select_from(RecordsRequest)) == 1
    assert marker["fixture_sha256"] == FIXTURE_HASH
    async def marker_loader(session):
        return await session.scalar(select(imports.c.demo_fixture))
    app.state.desktop_demo_marker = marker_loader
    await operation(api, proof, str(req_id), "draft-records-response", {"responseDraft":"Synthetic response", "citation":"Synthetic fixture"})
    await operation(api, proof, str(req_id), "approve-records-response")
    export = await api.post(f"/desktop/v1/requests/{req_id}/artifacts", json={"kind":"response"}, headers={"X-Townlight-Session":proof})
    assert export.status_code == 200, export.text
    assert marker["watermark"] in export.json()["content"]
    assert FIXTURE_HASH in export.json()["content"]
    public_proof = hmac.new(bytes.fromhex((root / "session-mac-secret.key").read_text()), b"townlight-native-public-records-v1", hashlib.sha256).hexdigest()
    public = await api.get("/desktop/v1/public/records-state", headers={"X-Townlight-Public":public_proof})
    assert public.status_code == 200
    assert public.json()["demo_fixture"] == marker
