"""Real managed bytes and SQL metadata for the accepted attachment workflow."""
import hashlib
import uuid

import pytest
from sqlalchemy import func, select

from app.models.document import Document
from app.models.records_files import RequestFileEvidence, RequestReleaseCopy
from app.models.audit import AuditLog
from tests.conftest import test_session_maker as session_factory
from tests.test_desktop_records import native_api  # noqa: F401
from tests.test_desktop_session import native_profile  # noqa: F401
from tests.test_desktop_records_lifecycle import intake, operation


def staged_file(app, name, contents):
    root = app.state.desktop_profile_root / "Data" / "files" / "records" / "staged"
    root.mkdir(parents=True, exist_ok=True)
    path = root / name
    path.write_bytes(contents)
    return {"original_path": f"synthetic-original/{name}", "stored_path": str(path),
            "file_name": name, "sha256": hashlib.sha256(contents).hexdigest(), "size_bytes": len(contents)}


@pytest.mark.asyncio
async def test_files_preserve_original_and_release_history_without_revoking_response(native_api):
    api, proof, actor_id, app = native_api
    request_id = await intake(api, proof)
    headers = {"X-Townlight-Session": proof}
    await operation(api, proof, request_id, "draft-records-response", {"responseDraft": "Approved text", "citation": "SYNTHETIC"})
    approved = await operation(api, proof, request_id, "approve-records-response")
    receipt = staged_file(app, "original.txt", b"Synthetic original with private detail")
    data = {"title": "Synthetic original", "citation": "FILE-1", "file": receipt}
    url = f"/desktop/v1/requests/{request_id}/documents"
    denied = await api.post(url, json=data)
    assert denied.status_code == 401
    attached = await api.post(url, json=data, headers=headers)
    assert attached.status_code == 200, attached.text
    view = attached.json()["request"]
    assert view["approved_at_unix_seconds"] == approved["request"]["approved_at_unix_seconds"]
    assert len(view["documents"]) == 1
    attachment = view["documents"][0]
    assert attachment["sha256"] == receipt["sha256"]
    duplicate = await api.post(url, json=data, headers=headers)
    assert duplicate.status_code == 200, duplicate.text
    assert len(duplicate.json()["request"]["documents"]) == 1
    release_url = f"{url}/{attachment['attachment_id']}/release-copy"
    for index in (1, 2):
        release = staged_file(app, f"release-{index}.txt", f"Synthetic public copy {index}".encode())
        response = await api.post(release_url, headers=headers, json={
            "status": "redacted copy", "note": "Human reviewed", "added_by": "Review label", "file": release,
        })
        assert response.status_code == 200, response.text
    view = response.json()["request"]
    assert view["documents"][0]["release_sha256"] == release["sha256"]
    assert view["documents"][0]["sha256"] == receipt["sha256"]
    assert view["approved_at_unix_seconds"] == approved["request"]["approved_at_unix_seconds"]
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RequestFileEvidence)) == 1
        assert await session.scalar(select(func.count()).select_from(RequestReleaseCopy)) == 2
        assert await session.scalar(select(func.count()).select_from(Document)) == 1
        entries = (await session.execute(select(AuditLog).where(AuditLog.action.in_(
            ["add-records-document", "add-records-release-copy"]
        )))).scalars().all()
        assert len(entries) == 3
        assert all(entry.user_id == actor_id for entry in entries)
    readback = await api.get(f"/desktop/v1/requests/{request_id}/view", headers=headers)
    assert readback.json() == view


@pytest.mark.asyncio
async def test_unverified_and_cross_request_files_accept_no_domain_change(native_api):
    api, proof, _, app = native_api
    headers = {"X-Townlight-Session": proof}
    request_id = await intake(api, proof)
    url = f"/desktop/v1/requests/{request_id}/documents"
    receipt = staged_file(app, "candidate.txt", b"Synthetic evidence")
    data = {"title": "Test evidence", "file": dict(receipt, sha256="0" * 64)}
    rejected = await api.post(url, json=data, headers=headers)
    assert rejected.status_code == 400, rejected.text
    outside = app.state.desktop_profile_root / "outside.txt"
    outside.write_bytes(b"Synthetic evidence")
    data["file"] = dict(receipt, stored_path=str(outside))
    rejected = await api.post(url, json=data, headers=headers)
    assert rejected.status_code == 400, rejected.text
    readback = await api.get(f"/desktop/v1/requests/{request_id}/view", headers=headers)
    assert readback.json()["documents"] == []
    attached = await api.post(url, json={"title": "Test evidence", "file": receipt}, headers=headers)
    assert attached.status_code == 200, attached.text
    attachment_id = attached.json()["request"]["documents"][0]["attachment_id"]
    other = await intake(api, proof)
    rejected = await api.post(f"/desktop/v1/requests/{other}/documents/{attachment_id}/release-copy",
                             headers=headers, json={"status": "redacted copy", "file": receipt})
    assert rejected.status_code == 400, rejected.text
    async with session_factory() as session:
        assert await session.scalar(select(func.count()).select_from(RequestReleaseCopy)) == 0
