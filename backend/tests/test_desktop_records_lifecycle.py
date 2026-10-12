"""P1/P3 accepted Records behavior, not a new policy or acceptance framework."""

from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import uuid

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from app.models.request import RecordsRequest
from app.schemas.request import RequestUpdate
from tests.conftest import test_session_maker as session_factory
from tests.test_desktop_records import INTAKE, native_api  # noqa: F401
from tests.test_desktop_session import native_profile  # noqa: F401


FIXTURE = json.loads((Path(__file__).parent / "fixtures/records-desktop-lifecycle-v2.json").read_text())


async def intake(api, proof):
    response = await api.post("/desktop/v1/requests", json=INTAKE,
                              headers={"X-Townlight-Session": proof})
    assert response.status_code == 201, response.text
    return response.json()["id"]


async def operation(api, proof, request_id, action, payload=None, expected_status=200):
    response = await api.post(f"/desktop/v1/requests/{request_id}/actions",
                              json={"action": action, "payload": payload or {}},
                              headers={"X-Townlight-Session": proof})
    assert response.status_code == expected_status, response.text
    return response.json()


@pytest.mark.asyncio
async def test_existing_non_file_lifecycle_uses_canonical_relations(native_api):
    api, proof, actor_id, _ = native_api
    request_id = await intake(api, proof)
    actions = {"request-records-clarification", "add-records-message", "assign-records-request",
               "record-records-search", "record-records-search-session",
               "add-records-exemption-review", "add-records-exemption-decision",
               "add-records-fee-line", "waive-records-fee", "draft-records-response",
               "approve-records-response"}
    for step in FIXTURE["lifecycle"]:
        if step["action"] not in actions or step.get("expect_error"):
            continue
        result = await operation(api, proof, request_id, step["action"], step.get("payload"))
        view = result["request"]
        expected = step["expected"]
        for key in ("assigned_to", "status"):
            if key in expected:
                assert view[key] == expected[key]
        for key in ("clarification_notes", "search_notes", "search_sessions", "exemption_reviews",
                    "exemption_decisions", "fee_line_items"):
            if key in expected:
                assert len(view[key]) == expected[key]
    assert view["approved_at_unix_seconds"] is not None
    assert view["fee_line_items"][0]["amount_cents"] == 1250
    assert view["search_sessions"][0]["results"][0]["citation"] == "PRA-2026-004"
    assert view["exemption_decisions"][0]["decision"] == "redact"
    assert view["messages"][0]["visibility"] == "requester thread"
    assert view["messages"][0]["body"].startswith("We received the narrowed")
    readback = await api.get(f"/desktop/v1/requests/{request_id}/view",
                             headers={"X-Townlight-Session": proof})
    assert readback.status_code == 200, readback.text
    assert readback.json() == view
    async with session_factory() as session:
        domain_entries = (await session.execute(select(AuditLog).where(
            AuditLog.action.in_(actions)
        ))).scalars().all()
        assert {entry.action for entry in domain_entries} == actions
        assert all(entry.user_id == actor_id for entry in domain_entries)
        req = await session.get(RecordsRequest, uuid.UUID(request_id))
        assert req.response_draft == view["response_draft"]


@pytest.mark.asyncio
async def test_only_changed_response_text_revokes_current_approval(native_api):
    api, proof, _, _ = native_api
    request_id = await intake(api, proof)
    await operation(api, proof, request_id, "draft-records-response",
                    {"responseDraft": "Original accepted response", "citation": "SYNTHETIC-001"})
    approved = (await operation(api, proof, request_id, "approve-records-response",
                                {"approvalNote": "First human approval"}))["request"]
    stamp = approved["approved_at_unix_seconds"]
    for action, payload in [
        ("assign-records-request", {"assignedTo": "Another officer"}),
        ("set-records-deadline", {"deadline": "2026-10-30", "deadlineBasis": "Reviewed basis"}),
        ("estimate-records-fee", {"feeEstimate": "$12.50 estimated"}),
        ("draft-records-response", {"responseDraft": "Original accepted response"}),
    ]:
        view = (await operation(api, proof, request_id, action, payload))["request"]
        assert view["approved_at_unix_seconds"] == stamp
        assert view["approval_notes"] == ["First human approval"]
    changed = (await operation(api, proof, request_id, "draft-records-response",
                               {"responseDraft": "Changed response requiring renewed review"}))["request"]
    assert changed["approved_at_unix_seconds"] is None
    assert changed["approval_notes"] == ["First human approval"]
    async with session_factory() as session:
        req = await session.get(RecordsRequest, uuid.UUID(request_id))
        assert req.approved_response_sha256 is None
    renewed = (await operation(api, proof, request_id, "approve-records-response"))["request"]
    assert renewed["approved_at_unix_seconds"] is not None
    assert renewed["approval_notes"] == ["First human approval"]


@pytest.mark.asyncio
async def test_invalid_command_and_money_accept_no_partial_work(native_api):
    api, proof, _, _ = native_api
    request_id = await intake(api, proof)
    await operation(api, proof, request_id, "add-records-fee-line",
                    {"feeLineDescription": "Invalid", "feeScheduleBasis": "Synthetic policy",
                     "feeLineAmount": "12.345"}, expected_status=422)
    await operation(api, proof, request_id, "assign-records-request",
                    {"assignedTo": "Officer", "actor": "admin"}, expected_status=422)
    await operation(api, proof, request_id, "approve-records-response", expected_status=400)
    after = await api.get(f"/desktop/v1/requests/{request_id}/view",
                          headers={"X-Townlight-Session": proof})
    assert after.status_code == 200, after.text
    assert after.json()["fee_line_items"] == []
    assert after.json()["approved_at_unix_seconds"] is None
    assert len(after.json()["timeline"]) == 1


@pytest.mark.asyncio
async def test_existing_web_writer_cannot_leave_native_approval_on_replaced_text(native_api):
    """The shared row must not acquire an approval bypass through another writer."""
    from app.requests.router import update_request

    _ = native_api
    async with session_factory() as session:
        from app.models.user import User
        actor = (await session.execute(select(User).where(
            User.email == "seed-admin@test.internal"
        ))).scalar_one()
        req = RecordsRequest(requester_name="Synthetic", description="Shared row",
                             created_by=actor.id, response_draft="Approved text",
                             approved_at=datetime.now(timezone.utc),
                             approved_response_sha256=hashlib.sha256(b"Approved text").hexdigest())
        session.add(req)
        await session.commit()
        request_id = req.id
        await update_request(request_id, RequestUpdate(response_draft="Replacement text"),
                             session=session, user=actor)
    async with session_factory() as session:
        saved = await session.get(RecordsRequest, request_id)
        assert saved.approved_at is None
        assert saved.approved_response_sha256 is None


@pytest.mark.asyncio
async def test_runtime_readiness_requires_the_lifecycle_schema(client, monkeypatch):
    """An intake-only schema is no longer enough for the changed domain app."""
    from sqlalchemy import text
    from tests.conftest import TEST_DATABASE_URL

    runtime_root = Path(__file__).resolve().parents[3] / "townlight/desktop/runtime/python-services"
    if not runtime_root.is_dir():
        pytest.skip("The runtime readiness proof requires the paired Townlight checkout.")
    monkeypatch.syspath_prepend(str(runtime_root))
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    from civicsuite_runtime.services import _domain_database_status

    assert _domain_database_status()["ok"] is True
    async with session_factory() as session:
        await session.execute(text("ALTER TABLE request_evidence_notes RENAME COLUMN content TO unavailable_content"))
        await session.commit()
    try:
        assert _domain_database_status() == {"ok": False, "reason": "domain-schema-unavailable"}
    finally:
        async with session_factory() as session:
            await session.execute(text("ALTER TABLE request_evidence_notes RENAME COLUMN unavailable_content TO content"))
            await session.commit()
