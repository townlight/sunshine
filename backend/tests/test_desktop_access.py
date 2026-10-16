"""Actual Access engine/storage through the native capability boundary.

Synthetic advice exercises persistence, not a claim of real-model inference.
"""
import hashlib
import hmac
import json

import pytest
from sqlalchemy import select

from app.models.audit import AuditLog
from tests.conftest import TEST_DATABASE_URL, test_session_maker as session_factory
from tests.test_desktop_records import native_api, native_profile  # noqa: F401


@pytest.mark.asyncio
async def test_access_review_uses_existing_engine_and_keeps_capabilities_separate(native_api):
    from civicaccess.access_review import AccessibilityReviewRepository, review_accessibility
    from civicsuite_runtime.access_bridge import router, ensure_native_schema
    api, proof, actor_id, app = native_api
    repository = AccessibilityReviewRepository(db_url=TEST_DATABASE_URL.replace("+asyncpg", "+psycopg2"))
    try:
        ensure_native_schema(repository.engine)
    finally:
        repository.engine.dispose()
    app.include_router(router)
    from civicsuite_runtime.records_snapshot import router as snapshot_router
    app.include_router(snapshot_router)
    endpoint = "/desktop/v1/access/reviews"
    data = {"title": "Sample notice", "body": "Please attend.", "hasAltText": False, "language": "en"}
    assert (await api.post(endpoint, json={**data, "ai_outcome": "unavailable"})).status_code == 401
    assert (await api.post(endpoint, json={**data, "ai_outcome": "unavailable"},
                           headers={"X-Townlight-Session": proof})).status_code == 403
    confidential = await api.post("/desktop/v1/requests", json={"requester": "Synthetic Resident",
        "summary": "Private trail request", "deadline": "2026-10-15"}, headers={"X-Townlight-Session": proof})
    assert confidential.status_code == 201, confidential.text

    # A clerk may use Access but must not gain Records through the shared actor resolver.
    root = app.state.desktop_profile_root
    staff_path = root / "config" / "staff-users.json"
    staff = json.loads(staff_path.read_text())
    staff[0]["role"] = "clerk"
    staff_path.write_text(json.dumps(staff))
    session_path = root / "config" / "local-session.json"
    native = json.loads(session_path.read_text())
    native["role"] = "clerk"
    message = f"{staff[0]['email']}\nclerk\n{native['expires_at_unix_seconds']}\n{staff[0]['passcode_hash']}"
    proof = hmac.new(bytes(range(32)), message.encode(), hashlib.sha256).hexdigest()
    native["session_hash"] = proof
    session_path.write_text(json.dumps(native))
    headers = {"X-Townlight-Session": proof}
    assert (await api.get("/desktop/v1/records-state", headers=headers)).status_code == 403
    context = await api.post("/desktop/v1/access/review-context", json=data, headers=headers)
    assert context.status_code == 200, context.text
    assert "missing-alt-text" in context.json()["prompt"]
    expected = review_accessibility(title=data["title"], body=data["body"], has_alt_text=False, language="en")
    for outcome in ("unavailable", "failed", "generated"):
        advice = {"ai_analysis": "Synthetic advisory text", "ai_analysis_model": "synthetic-model"} if outcome == "generated" else {}
        response = await api.post(endpoint, json={**data, "ai_outcome": outcome, **advice}, headers=headers)
        assert response.status_code == 200, response.text
        saved = response.json()["access"]["reviews"][-1]
        assert saved["status"] == expected.status
        assert [f["code"] for f in saved["findings"]] == [f.code for f in expected.findings]
        assert saved["ai_analysis"] == advice.get("ai_analysis")
    state = (await api.get("/desktop/v1/access/state", headers=headers)).json()
    assert len(state["reviews"]) == 3
    assert {a["actor"] for a in state["audit_events"]} == {str(actor_id)}
    plan = await api.post(f"{endpoint}/{saved['review_id']}/export", headers=headers)
    assert plan.status_code == 200, plan.text
    prepared = plan.json()
    output = root / "Data" / "exports" / "access" / prepared["file_name"]
    output.parent.mkdir(parents=True)
    output.write_bytes(b"wrong bytes")
    finalize = f"/desktop/v1/access/exports/{prepared['artifact_id']}/complete"
    assert (await api.post(finalize, json={"export_path": str(output)}, headers=headers)).status_code == 400
    output.write_bytes(prepared["content"].encode())
    output.with_name(output.name + ".manifest.json").write_text(json.dumps({
        "sha256": prepared["sha256"], "size_bytes": output.stat().st_size, "export_file": output.name}))
    for _ in range(2):
        result = await api.post(finalize, json={"export_path": str(output)}, headers=headers)
        assert result.status_code == 200, result.text
    deleted = await api.post(f"{endpoint}/{saved['review_id']}/delete", headers=headers)
    assert deleted.status_code == 200, deleted.text
    assert len(deleted.json()["access"]["reviews"]) == 2
    assert len(deleted.json()["access"]["audit_events"]) == 5
    assert output.is_file()  # Deleting the review never erases its prior export.
    async with session_factory() as session:
        audits = (await session.execute(select(AuditLog).where(AuditLog.resource_type == "access"))).scalars().all()
        assert len(audits) == 5
        assert {a.user_id for a in audits} == {actor_id}
    for data, status in [
        ({"action": "form-plan", "formName": "Request", "fields": ["name", "contact", "request"]}, "form-plan-created"),
        ({"action": "publishing-workflow", "title": "Notice"}, "blocked"),
        ({"action": "ada-title-ii", "serviceArea": "Library"}, "needs-staff-review"),
        ({"action": "tagged-pdf", "headingLevels": [1, 3]}, "needs-fixes"),
    ]:
        result = await api.post("/desktop/v1/access/tools", json=data, headers=headers)
        assert result.status_code == 200, result.text
        assert result.json()["result"]["status"] == status
    for action in ("plain-language", "language-variant"):
        payload = {"action": action, "text": "Commence work prior to Friday.", "language": "es"}
        assert (await api.post("/desktop/v1/access/rewrite-context", json=payload, headers=headers)).status_code == 200
        result = await api.post("/desktop/v1/access/rewrite-result", json={**payload, "outcome": "unavailable"}, headers=headers)
        assert result.status_code == 200, result.text
        assert "sample" in result.json()["message"]
        failed = await api.post("/desktop/v1/access/rewrite-result", json={**payload, "outcome": "failed"}, headers=headers)
        assert failed.status_code == 422  # Failed inference cannot silently substitute sample output.
    private = await api.post("/desktop/v1/suite/search", json={"query": "Private trail"}, headers=headers)
    assert private.status_code == 200, private.text
    assert private.json()["search_results"] == []
    assert private.json()["state"]["records_requests"] == []
    assert private.json()["state"]["notification_events"] == []
    own = await api.post("/desktop/v1/suite/search", json={"query": "Sample notice"}, headers=headers)
    assert own.status_code == 200, own.text
    assert len(own.json()["search_results"]) == 2
    assert {r["module_id"] for r in own.json()["search_results"]} == {"civicaccess"}
    # Records-only view must not leak Access audit summaries either.
    from app.desktop_bridge.projection import records_state
    async with session_factory() as session:
        view = await records_state(session)
        assert all(item.module_id == "civicrecords-ai" for item in view.audit_entries)
    from civicsuite_runtime.access_bridge import review_advice
    surviving = own.json()["state"]["access"]["reviews"][0]
    canonical = surviving["canonical_review_id"]
    async with session_factory() as session:
        await session.execute(review_advice.update().where(review_advice.c.review_id == canonical)
                              .values(legacy_id="access-review-historical"))
        await session.commit()
    refreshed = (await api.get("/desktop/v1/access/state", headers=headers)).json()
    assert any(row["review_id"] == "access-review-historical" and row["canonical_review_id"] == canonical for row in refreshed["reviews"])
    app.state.desktop_domain_enabled = False
    assert (await api.get("/desktop/v1/access/state", headers=headers)).status_code == 503
