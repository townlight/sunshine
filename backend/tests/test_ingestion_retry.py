"""Tests for document re-ingestion retry (Item 12 — Debt Sprint)."""

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_re_ingest_requires_failed_status(client: AsyncClient, admin_token: str):
    """POST /datasources/documents/{id}/re-ingest rejects non-failed docs."""
    import uuid
    from sqlalchemy import select
    from tests.conftest import test_session_maker
    from townlight_records.models.user import User
    from townlight_records.models.document import DataSource, Document, IngestionStatus, SourceType

    # Seed the state this endpoint rejects directly. Uploading queues unrelated
    # ingestion work and requires the optional standalone Redis deployment.
    async with test_session_maker() as session:
        user = (await session.execute(select(User))).scalars().first()
        source = DataSource(name="retry-fixture-" + uuid.uuid4().hex,
                            source_type=SourceType.MANUAL_DROP,
                            connection_config={}, created_by=user.id)
        session.add(source)
        await session.flush()
        document = Document(source_id=source.id, source_path="synthetic-retry.txt",
                            filename="synthetic-retry.txt", file_type="txt",
                            file_hash="a" * 64, ingestion_status=IngestionStatus.PENDING)
        session.add(document)
        await session.commit()
        document_id = document.id
    resp = await client.post(
        f"/datasources/documents/{document_id}/re-ingest",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 400
    assert "Can only re-ingest failed documents" in resp.json()["detail"]



@pytest.mark.asyncio
async def test_re_ingest_requires_auth(client: AsyncClient):
    """POST /datasources/documents/{id}/re-ingest without auth returns 401."""
    import uuid
    resp = await client.post(f"/datasources/documents/{uuid.uuid4()}/re-ingest")
    assert resp.status_code == 401
