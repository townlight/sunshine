"""Local public intake is anonymous, not an invented staff account."""
import hashlib
import hmac
import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

from app.models.request import RecordsRequest
from app.models.audit import AuditLog
from tests.conftest import test_session_maker as session_factory
from tests.test_desktop_records import native_api as native_api # noqa: F401
from tests.test_desktop_session import native_profile as native_profile # noqa: F401
from tests.test_desktop_records_lifecycle import operation


@pytest.mark.asyncio
async def test_public_contact_boundary_and_actual_anonymous_actor(native_api):
    api, staff_proof, _, app = native_api
    key = bytes.fromhex((app.state.desktop_profile_root / "session-mac-secret.key").read_text().strip())
    proof = hmac.new(key, b"townlight-native-public-records-v1", hashlib.sha256).hexdigest()
    public = {"X-Townlight-Public": proof}
    payload = {"requester": "Synthetic resident", "requesterContact": "test@example.invalid", "summary": "Synthetic request"}
    denied = await api.post("/desktop/v1/public/requests", json=payload)
    assert denied.status_code == 401
    wrong_proof = await api.post("/desktop/v1/public/requests", json=payload, headers={"X-Townlight-Public": staff_proof})
    assert wrong_proof.status_code == 401
    created = await api.post("/desktop/v1/public/requests", json=payload, headers=public)
    assert created.status_code == 200, created.text
    view = created.json()["state"]["records_requests"][0]
    request_id, tracking = view["request_id"], view["public_tracking_number"]
    assert view["requester_contact"] == ""
    assert view["deadline"] == "Pending clerk deadline review"
    assert view["deadline_reviewed_at_unix_seconds"] is None
    await operation(api, staff_proof, request_id, "draft-records-response", {"responseDraft": "Private draft", "citation": "SYN-1"})
    await operation(api, staff_proof, request_id, "add-records-exemption-review", {"exemptionNote": "Private review"})
    public_state = await api.get("/desktop/v1/public/records-state", headers=public)
    assert public_state.json()["records_requests"] == []
    bad = await api.post("/desktop/v1/public/lookup", json={"trackingNumber": tracking, "requesterContact": "wrong"}, headers=public)
    assert bad.json()["accepted"] is False
    message = await api.post("/desktop/v1/public/messages", headers=public, json={
        "trackingNumber": tracking.lower(), "requesterContact": "TEST@EXAMPLE.INVALID", "publicRequestMessage": "Resident clarification",
    })
    assert message.status_code == 200, message.text
    matched = message.json()["state"]["records_requests"][0]
    assert matched["response_draft"] == "" and matched["exemption_reviews"] == []
    assert matched["messages"][0]["body"] == "Resident clarification"
    async with session_factory() as session:
        req = await session.get(RecordsRequest, uuid.UUID(request_id))
        assert req.created_by is None
        entries = (await session.execute(select(AuditLog).where(AuditLog.action.in_(
            ["submit-public-records-request", "add-public-records-message"]
        )))).scalars().all()
        assert len(entries) == 2 and all(entry.user_id is None for entry in entries)
        # Projection-only fixture: real fulfillment is covered by artifact test.
        req.fulfilled_at = datetime.now(timezone.utc)
        await session.commit()
    released = await api.post("/desktop/v1/public/lookup", headers=public, json={
        "trackingNumber": tracking, "requesterContact": payload["requesterContact"],
    })
    assert released.json()["state"]["records_requests"][0]["messages"] == []
    forbidden = await api.get("/desktop/v1/records-state", headers={"X-Townlight-Session": proof})
    assert forbidden.status_code == 401
    app.state.desktop_domain_enabled = False
    disabled = await api.post("/desktop/v1/public/requests", json=payload, headers=public)
    assert disabled.status_code == 503
