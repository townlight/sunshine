"""Canonical Records attachment metadata; the native shell stages file bytes.

No request accepts a caller's hash as proof. Only files in the configured
managed Records directory are read, and their size/hash are checked here.
"""
import hashlib
import json
from pathlib import Path
import uuid

from sqlalchemy import select, text

from app.models.document import DataSource, Document, SourceType
from app.models.records_files import RequestFileEvidence, RequestReleaseCopy
from app.models.request import RequestDocument, RequestStatus
from app.requests import workflow


def managed_records_root(profile_root: Path) -> Path:
    locations = profile_root / "config" / "locations.json"
    if locations.exists():
        try:
            data_root = Path(json.loads(locations.read_text(encoding="utf-8"))["data_root"])
            if not data_root.is_absolute():
                raise ValueError("Relative data root")
        except (OSError, ValueError, KeyError, TypeError):
            raise ValueError("The configured Records data location is invalid.") from None
    else:
        data_root = profile_root / "Data"
    return (data_root / "files" / "records").resolve()


def verify_managed_file(profile_root: Path, receipt) -> Path:
    try:
        path = Path(receipt.stored_path).resolve(strict=True)
        if not path.is_relative_to(managed_records_root(profile_root)) or not path.is_file():
            raise ValueError("Outside managed files")
        with path.open("rb") as stream:
            digest = hashlib.file_digest(stream, "sha256").hexdigest()
            size = stream.tell()
        # file_digest can bypass file.tell buffering; stat is authoritative.
        size = path.stat().st_size
        if digest != receipt.sha256 or size != receipt.size_bytes:
            raise ValueError("Hash/size mismatch")
    except (OSError, ValueError):
        raise ValueError("Managed Records file is missing, outside its store, or does not match its recorded bytes.") from None
    return path


async def attach_document(session, req, actor, data, profile_root):
    workflow.ensure_active(req)
    path = verify_managed_file(profile_root, data.file)
    # Dedicated source identity is a domain source, not another file/state store.
    # Serialize its first creation across requests without a competing unique insert.
    await session.execute(text("SELECT pg_advisory_xact_lock(7265636)"))
    source_name = "Townlight managed Records evidence"
    source = await session.scalar(select(DataSource).where(DataSource.name == source_name))
    if source is None:
        source = DataSource(name=source_name, source_type=SourceType.MANUAL_DROP,
                            connection_config={}, created_by=actor.user.id)
        session.add(source)
        await session.flush()
    existing = (await session.execute(select(RequestFileEvidence, Document).join(
        RequestDocument, RequestDocument.id == RequestFileEvidence.id
    ).join(Document, RequestDocument.document_id == Document.id).where(
        RequestFileEvidence.request_id == req.id, Document.source_path == str(path)
    ))).first()
    if existing:
        evidence, document = existing
        if (evidence.title, evidence.original_path, evidence.citation, document.file_hash) != (
                data.title, data.file.original_path, data.citation, data.file.sha256):
            raise ValueError("This staged file already has different attachment metadata.")
        return "Records document already attached; no duplicate evidence was created."
    document = Document(source_id=source.id, source_path=str(path), filename=data.file.file_name,
                        file_type=path.suffix.lstrip(".")[:50], file_hash=data.file.sha256,
                        file_size=data.file.size_bytes, display_name=data.title[:500], original_locked=True)
    session.add(document)
    await session.flush()
    link = RequestDocument(request_id=req.id, document_id=document.id, attached_by=actor.user.id,
                           relevance_note=data.citation)
    session.add(link)
    await session.flush()
    session.add(RequestFileEvidence(id=link.id, request_id=req.id, title=data.title,
                                   original_path=data.file.original_path, citation=data.citation,
                                   added_by="records staff",
                                   position=await workflow.next_position(session, RequestFileEvidence, req.id)))
    if data.citation:
        await workflow.add_note(session, req, actor, "citation", data.citation)
    await workflow.record_progress(
        session, req, actor, action="add-records-document", status="document attached",
        canonical_status=RequestStatus.IN_REVIEW, timeline_action="document attached",
        timeline_note=f"Attached {data.title} from {data.file.file_name}; sha256 {data.file.sha256}.",
        public_label="Responsive records under review",
        public_summary="Potentially responsive records were added for staff review.",
        audit_note=f"Attached records document {data.title}; sha256 {data.file.sha256}; {data.file.size_bytes} bytes.",
    )
    return f"Records document evidence saved into local profile: {path}."


async def attach_release_copy(session, req, actor, attachment_id: uuid.UUID, data, profile_root):
    workflow.ensure_active(req)
    evidence = await session.get(RequestFileEvidence, attachment_id)
    if evidence is None or evidence.request_id != req.id:
        raise ValueError("The selected records document was not found in this request.")
    path = verify_managed_file(profile_root, data.file)
    existing = await session.scalar(select(RequestReleaseCopy).where(RequestReleaseCopy.stored_path == str(path)))
    if existing:
        if (existing.attachment_id, existing.sha256, existing.status, existing.note, existing.added_by) != (
                attachment_id, data.file.sha256, data.status, data.note, data.added_by or "records staff"):
            raise ValueError("This staged file already has different release-copy metadata.")
        return "Release copy already attached; no duplicate evidence was created."
    session.add(RequestReleaseCopy(
        request_id=req.id, attachment_id=attachment_id, original_path=data.file.original_path,
        stored_path=str(path), file_name=data.file.file_name, sha256=data.file.sha256,
        size_bytes=data.file.size_bytes, status=data.status, note=data.note,
        added_by=data.added_by or "records staff", actor_id=actor.user.id,
        position=await workflow.next_position(session, RequestReleaseCopy, req.id),
    ))
    await workflow.record_progress(
        session, req, actor, action="add-records-release-copy", status="release copy attached",
        canonical_status=RequestStatus.IN_REVIEW, timeline_action="release copy attached",
        timeline_note=f"{data.status} attached for {evidence.title}; sha256 {data.file.sha256}. {data.note or 'No release note recorded.'}",
        public_label="Release copy prepared",
        public_summary="A release-ready or redacted copy was prepared for this request.",
        audit_note=f"Attached {data.status} for {evidence.title}; sha256 {data.file.sha256}; {data.file.size_bytes} bytes; by {data.added_by or 'records staff'}. {data.note}",
    )
    return f"Records {data.status} evidence saved into local profile: {path}."
