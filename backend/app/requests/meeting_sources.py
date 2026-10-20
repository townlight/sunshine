"""Attach an authorized Meetings snapshot using canonical Records evidence."""
import hashlib
import uuid
from sqlalchemy import select
from app.audit.logger import write_audit_log
from app.desktop_bridge.schemas import AttachDocument, ManagedFileReceipt
from app.models.document import Document
from app.requests import files, workflow


async def attach_snapshot(session, req, actor, source, profile_root):
    workflow.ensure_active(req)
    content = source["text"].encode("utf-8")
    digest = hashlib.sha256(content).hexdigest()
    if digest != source["sha256"] or source["visibility"] != "public":
        raise ValueError("Meetings source integrity/permission check failed.")
    # Same request + source version + hash has one managed path. Retrying after a
    # lost response reuses existing evidence, not a new attachment or audit event.
    identity = uuid.uuid5(uuid.NAMESPACE_URL, f"{req.id}:{source['source_id']}:{digest}")
    directory = files.managed_records_root(profile_root) / "meetings" / str(identity)
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / f"{source['kind']}.txt"
    try:
        with path.open("xb") as output:
            output.write(content)
    except FileExistsError:
        if path.read_bytes() != content:
            raise ValueError("Existing Meetings evidence differs; it was not overwritten.") from None
    data = AttachDocument(title=source["title"], citation=source["citation"],
        file=ManagedFileReceipt(original_path=source["source_id"], stored_path=str(path),
            file_name=path.name, sha256=digest, size_bytes=len(content)))
    message = await files.attach_document(session, req, actor, data, profile_root)
    document = await session.scalar(select(Document).where(Document.source_path == str(path)))
    provenance = {key: value for key, value in source.items() if key != "text"}
    if not document.metadata_:
        document.metadata_ = {"meetings_source": provenance}
        await write_audit_log(session=session, action="attach-meetings-source",
            resource_type="request", resource_id=str(req.id), user_id=actor.user.id,
            details=provenance, commit=False)
    elif document.metadata_.get("meetings_source") != provenance:
        raise ValueError("Existing source provenance differs; no metadata was replaced.")
    return message
