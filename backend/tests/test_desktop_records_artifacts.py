"""Export intent versus real bytes versus completed Records state."""
import hashlib
import json
from pathlib import Path

import pytest
from sqlalchemy import func, select

from app.models.records_artifacts import RequestArtifact, RequestPublication
from tests.conftest import test_session_maker as session_factory
from tests.test_desktop_records import native_api  # noqa: F401
from tests.test_desktop_session import native_profile  # noqa: F401
from tests.test_desktop_records_lifecycle import intake, operation


def write_test_export(app, plan):
    # This fixture supplies actual bytes for API verification. Native writer
    # behavior has its own Rust test; this is not an installed UI claim.
    root = app.state.desktop_profile_root / "Data" / "exports" / "records"
    root.mkdir(parents=True, exist_ok=True)
    path = root / plan["file_name"]
    path.write_bytes(plan["content"].encode())
    path.with_name(path.name + ".manifest.json").write_text(json.dumps({
        "sha256": plan["sha256"], "size_bytes": len(plan["content"].encode()), "export_file": path.name,
    }))
    return path


async def prepare(api, proof, request_id, kind, expected=200):
    response = await api.post(f"/desktop/v1/requests/{request_id}/artifacts", json={"kind": kind},
                              headers={"X-Townlight-Session": proof})
    assert response.status_code == expected, response.text
    return response.json()


async def complete(api, proof, request_id, plan, path, expected=200):
    response = await api.post(f"/desktop/v1/requests/{request_id}/artifacts/{plan['artifact_id']}/complete",
                              json={"export_path": str(path)}, headers={"X-Townlight-Session": proof})
    assert response.status_code == expected, response.text
    return response.json()


@pytest.mark.asyncio
async def test_verified_exports_fulfillment_and_closure(native_api):
    api, proof, actor_id, app = native_api
    request_id = await intake(api, proof)
    await prepare(api, proof, request_id, "response", 400)
    await prepare(api, proof, request_id, "release-package", 400)
    await operation(api, proof, request_id, "record-records-search-session", {
        "searchQuery": "Synthetic trail", "searchLocations": "Synthetic files", "searchResultTitle": "Public record",
        "searchResultCitation": "SYN-1", "searchResultSummary": "Synthetic evidence",
    })
    await operation(api, proof, request_id, "add-records-exemption-decision", {
        "exemptionSource": "SYN-1", "exemptionKind": "Human review", "exemptionFinding": "No restriction",
        "exemptionDecision": "release", "exemptionBasis": "Synthetic test decision",
    })
    await operation(api, proof, request_id, "draft-records-response", {"responseDraft": "Approved synthetic response"})
    await operation(api, proof, request_id, "approve-records-response", {"approvalNote": "Approved by human"})
    await operation(api, proof, request_id, "fulfill-records-request", expected_status=400)
    for kind in ("release-package", "response"):
        plan = await prepare(api, proof, request_id, kind)
        assert hashlib.sha256(plan["content"].encode()).hexdigest() == plan["sha256"]
        path = write_test_export(app, plan)
        result = await complete(api, proof, request_id, plan, path)
        same = await complete(api, proof, request_id, plan, path)
        assert same["request"] == result["request"]
    assert len(result["request"]["exports"]) == 1
    assert len(result["request"]["release_packages"]) == 1
    fulfilled = await operation(api, proof, request_id, "fulfill-records-request")
    assert fulfilled["request"]["fulfilled_at_unix_seconds"] is not None
    closed = await operation(api, proof, request_id, "close-records-request")
    assert closed["request"]["status"] == "closed"
    await operation(api, proof, request_id, "draft-records-response", {"responseDraft": "Too late"}, expected_status=400)
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RequestArtifact)) == 2
        publications = (await session.execute(select(RequestPublication))).scalars().all()
        assert len(publications) == 1 and publications[0].actor_id == actor_id
    assert path.exists()


@pytest.mark.asyncio
async def test_incomplete_or_superseded_export_never_becomes_success(native_api):
    api, proof, _, app = native_api
    request_id = await intake(api, proof)
    await operation(api, proof, request_id, "draft-records-response", {"responseDraft": "Original", "citation": "SYN-1"})
    await operation(api, proof, request_id, "approve-records-response", {"approvalNote": "Historical approval"})
    plan = await prepare(api, proof, request_id, "response")
    path = write_test_export(app, plan)
    path.write_bytes(b"Tampered export")
    await complete(api, proof, request_id, plan, path, 400)
    path.write_bytes(plan["content"].encode())
    await operation(api, proof, request_id, "draft-records-response", {"responseDraft": "Changed"})
    await complete(api, proof, request_id, plan, path, 400)
    await operation(api, proof, request_id, "approve-records-response")
    # Even renewed approval cannot finalize the old response's prepared bytes.
    await complete(api, proof, request_id, plan, path, 400)
    current = await api.get(f"/desktop/v1/requests/{request_id}/view", headers={"X-Townlight-Session": proof})
    assert current.json()["exports"] == []
    assert current.json()["approval_notes"] == ["Historical approval"]
    async with session_factory() as session:
        row = await session.scalar(select(RequestArtifact))
        assert row.completed_at is None and row.export_path is None
    assert path.exists()  # failed finalization never removes evidence
