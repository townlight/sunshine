"""Keep native HTTP audit evidence when route instances exceed indexed limits."""
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from app.audit import middleware
from app.audit.logger import verify_chain
from app.database import get_async_session
from app.main import create_app
from app.models.audit import AuditLog
from tests.conftest import override_get_session, test_session_maker as session_maker


@pytest.mark.asyncio
async def test_native_http_audit_keeps_long_route_evidence(client, tmp_path, monkeypatch):
    # The normal fixture creates a dedicated migrated test database. Mount the real
    # supervised native router; unauthenticated writes must remain denied and logged.
    app = create_app(
        desktop_profile_root=tmp_path,
        desktop_enabled_modules=frozenset({"civiccore", "civicrecords-ai"}),
        desktop_domain_enabled=True,
    )
    app.dependency_overrides[get_async_session] = override_get_session
    monkeypatch.setattr(middleware, "async_session_maker", session_maker)
    request_id, document_id = uuid.uuid4(), uuid.uuid4()
    paths = [
        "/desktop/v1/requests",
        f"/desktop/v1/requests/{request_id}/documents/{document_id}/release-copy",
        f"/desktop/v1/requests/{'x' * 260}/documents/{document_id}/release-copy",
    ]
    assert len("POST " + paths[1]) > 100
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as native:
        for path in paths:
            response = await native.post(path, json={})
            assert response.status_code in (401, 403)
            async with session_maker() as session:
                entries = (await session.scalars(
                    select(AuditLog).where(AuditLog.resource_type == "http_request")
                    .order_by(AuditLog.id)
                )).all()
                matching = [entry for entry in entries if entry.details["path"] == path]
                assert len(matching) == 1, f"Missing HTTP audit for {path}"
                entry = matching[0]
                assert entry.details["method"] == "POST"
                assert entry.details["status_code"] == response.status_code
                assert entry.user_id is None
                assert len(entry.action) <= 100
                assert len(entry.resource_id) <= 255
                if len("POST " + path) <= 100:
                    assert entry.action == "POST " + path
                if len(path) <= 255:
                    assert entry.resource_id == path
                valid, count, error = await verify_chain(session)
                assert valid, error
                assert count >= len(entries)
