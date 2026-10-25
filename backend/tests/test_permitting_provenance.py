"""Affected Records gate: attachment cannot launder revoked Permitting evidence."""
import asyncio
import hashlib
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from app.requests.planning_sources import validate_document


def test_permitting_document_rechecks_provider_and_exact_bytes():
    text = '{"public_summary":"Fictional reviewed intake."}'
    digest = hashlib.sha256(text.encode()).hexdigest()
    source = dict(source_id="permitting:fixture", text=text, sha256=digest, visibility="public")
    available = [source]
    document = SimpleNamespace(file_hash=digest,
        metadata_={"permitting_source":{"source_id":source["source_id"], "sha256":digest}})
    session = SimpleNamespace(info={"permitting_source_provider":lambda **_: available})
    asyncio.run(validate_document(session, document))
    for rows in ([], [{**source,"visibility":"staff_only"}], [{**source,"text":"changed"}]):
        available[:] = rows
        with pytest.raises(HTTPException) as denied:
            asyncio.run(validate_document(session, document))
        assert denied.value.status_code == 503
    session.info.clear()
    with pytest.raises(HTTPException):
        asyncio.run(validate_document(session, document))
