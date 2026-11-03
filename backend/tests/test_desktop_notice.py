"""Notice transport and canonical Records handoff on the isolated test database."""
import base64
import hashlib
import hmac
import json

import pytest
from sqlalchemy import create_engine

from tests.conftest import TEST_DATABASE_URL
from tests.test_desktop_records import native_api as native_api, native_profile as native_profile, INTAKE  # noqa: F401


@pytest.mark.asyncio
async def test_notice_lifecycle_authority_and_verified_records_readback(native_api, monkeypatch):
    from townlight_notice.workflow import NoticeWorkflow
    from townlight_runtime.notice_bridge import router
    api, proof, actor_id, app = native_api
    monkeypatch.setenv("DATABASE_URL", TEST_DATABASE_URL)
    engine = create_engine(TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    NoticeWorkflow(engine)
    engine.dispose()
    app.include_router(router)
    headers = {"X-Townlight-Session": proof}
    endpoint = "/desktop/v1/notice"
    assert (await api.get(endpoint + "/notices")).status_code == 401
    assert (await api.get(endpoint + "/notices", headers=headers)).status_code == 403
    app.state.desktop_enabled_modules |= {"townlight_notice"}
    # Module availability alone cannot grant the records-only account Notice.
    assert (await api.get(endpoint + "/notices", headers=headers)).status_code == 403
    root = app.state.desktop_profile_root
    staff_path = root / "config/staff-users.json"
    session_path = root / "config/local-session.json"
    staff = json.loads(staff_path.read_text())
    native = json.loads(session_path.read_text())
    staff[0]["role"] = native["role"] = "city-staff"
    message = f"{staff[0]['email']}\ncity-staff\n{native['expires_at_unix_seconds']}\n{staff[0]['passcode_hash']}"
    native["session_hash"] = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    staff_path.write_text(json.dumps(staff))
    session_path.write_text(json.dumps(native))
    headers = {"X-Townlight-Session": native["session_hash"]}
    document = dict(title="Synthetic hearing", body="Attend at City Hall.",
                    notice_type="public hearing", statutory_basis="Staff-reviewed synthetic authority",
                    event_date="2026-12-01", lead_days=10)
    response = await api.post(endpoint + "/notices", json=document, headers=headers)
    assert response.status_code == 201, response.text
    saved = response.json()
    path = endpoint + "/notices/" + saved["notice_id"]
    assert (await api.post(path + "/approval", json={"sequence": 1}, headers=headers)).status_code == 422
    response = await api.post(path + "/review", json={"sequence": 1, "note": "Checked source and date"}, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    response = await api.post(path + "/approval", json={"sequence": saved["sequence"]}, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    assert saved["approval"]["actor"] == str(actor_id)
    assert (await api.post(path + "/archive", json={"sequence": saved["sequence"]}, headers=headers)).status_code == 422
    response = await api.post(path + "/proof", json={"sequence": saved["sequence"],
        "filename": "posting-receipt.txt", "content_base64": base64.b64encode(b"Synthetic actual proof bytes").decode(),
        "location": "City Hall board", "published_at": "2026-11-02T12:00:00-07:00"}, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    response = await api.post(path + "/archive", json={"sequence": saved["sequence"]}, headers=headers)
    assert response.status_code == 200, response.text
    saved = response.json()
    archive_path = endpoint + "/archives/" + saved["archive_id"]
    exported = await api.get(archive_path, headers=headers)
    assert exported.status_code == 200, exported.text
    archive = exported.json()
    assert hashlib.sha256(base64.b64decode(archive["content_base64"])).hexdigest() == archive["sha256"]
    request = await api.post("/desktop/v1/requests", json=INTAKE, headers=headers)
    assert request.status_code == 201, request.text
    request_id = request.json()["id"]
    for _ in range(2):
        handoff = await api.post(archive_path + "/records", json={"request_id": request_id}, headers=headers)
        assert handoff.status_code == 200, handoff.text
        assert handoff.json()["sha256"] == archive["sha256"]
    readback = await api.get(f"/desktop/v1/requests/{request_id}/view", headers=headers)
    assert readback.status_code == 200, readback.text
    assert archive["sha256"] in readback.text
    assert len(readback.json()["documents"]) == 1
    persisted = await api.get(path, headers=headers)
    assert persisted.json()["notice"]["state"] == "archived"
    assert {event["actor"] for event in persisted.json()["history"]} == {str(actor_id)}
