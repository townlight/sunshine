"""Affected Records gate: attachment cannot launder revoked Inspections evidence."""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from app.requests.planning_sources import validate_document


def test_inspections_document_rechecks_provider_and_exact_bytes():
    text = '{"public_summary":"Fictional reviewed intake."}'
    digest = hashlib.sha256(text.encode()).hexdigest()
    source = dict(source_id="inspections:fixture", text=text, sha256=digest, visibility="public")
    available = [source]
    document = SimpleNamespace(file_hash=digest,
        metadata_={"inspections_source":{"source_id":source["source_id"], "sha256":digest}})
    session = SimpleNamespace(info={"inspections_source_provider":lambda **_: available})
    asyncio.run(validate_document(session, document))
    for rows in ([], [{**source,"visibility":"staff_only"}], [{**source,"text":"changed"}]):
        available[:] = rows
        with pytest.raises(HTTPException) as denied:
            asyncio.run(validate_document(session, document))
        assert denied.value.status_code == 503
    session.info.clear()
    with pytest.raises(HTTPException):
        asyncio.run(validate_document(session, document))


@pytest.mark.parametrize("provider_available", [True, False])
def test_shared_session_preserves_inspections_provenance_provider(monkeypatch, provider_available):
    """Suite snapshots use the shared dependency, without native_records_user."""
    from app import database

    text = '{"public_summary":"Fictional reviewed intake."}'
    digest = hashlib.sha256(text.encode()).hexdigest()
    source = dict(source_id="inspections:fixture", text=text, sha256=digest, visibility="public")
    def provider(**_):
        return [source]

    planning_provider = object()
    state = SimpleNamespace(desktop_planning_sources=planning_provider)
    if provider_available:
        state.desktop_inspections_sources = provider
    request = SimpleNamespace(app=SimpleNamespace(state=state))
    session = SimpleNamespace(info={})

    class SessionContext:
        async def __aenter__(self):
            return session

        async def __aexit__(self, *args):
            return False

    monkeypatch.setattr(database, "async_session_maker", SessionContext)
    document = SimpleNamespace(file_hash=digest,
        metadata_={"inspections_source":{"source_id":source["source_id"], "sha256":digest}})

    async def read_shared_evidence():
        sessions = database.get_async_session(request)
        try:
            shared = await anext(sessions)
            assert shared.info["planning_source_provider"] is planning_provider
            if provider_available:
                await validate_document(shared, document)
                assert shared.info["inspections_source_provider"] is provider
            else:
                with pytest.raises(HTTPException) as denied:
                    await validate_document(shared, document)
                assert denied.value.status_code == 503
        finally:
            await sessions.aclose()

    asyncio.run(read_shared_evidence())
