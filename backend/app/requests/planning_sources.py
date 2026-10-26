"""Recheck selected Planning/Permitting evidence; attachment never grants access."""
import hashlib

from fastapi import HTTPException
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.models.document import Document
from app.models.request import RequestDocument


async def validate_document(session, document):
    for origin in ("planning", "permitting", "inspections"):
        await _validate_origin(session, document, origin)


async def _validate_origin(session, document, origin):
    provenance = (document.metadata_ or {}).get(f"{origin}_source")
    if provenance is None:
        return
    provider = session.info.get(f"{origin}_source_provider")
    try:
        if not callable(provider):
            raise ValueError("Provider unavailable")
        sources = await run_in_threadpool(provider, source_id=provenance["source_id"])
        if len(sources) != 1:
            raise ValueError("Source unavailable")
        source = sources[0]
        digest = hashlib.sha256(source["text"].encode("utf-8")).hexdigest()
        if (source["visibility"] != "public" or source["source_id"] != provenance["source_id"]
                or source["sha256"] != digest or provenance["sha256"] != digest
                or document.file_hash != digest):
            raise ValueError("Source changed or restricted")
    except Exception:
        raise HTTPException(503, f"{origin.capitalize()} evidence unavailable or restricted; no cached release permitted.") from None


async def validate_request(session, request_id):
    documents = (await session.execute(select(Document).join(
        RequestDocument, RequestDocument.document_id == Document.id
    ).where(RequestDocument.request_id == request_id))).scalars().all()
    for document in documents:
        await validate_document(session, document)
