"""Read-only translation of canonical Records rows into the accepted view."""

from collections import defaultdict

from sqlalchemy import select

from app.desktop_bridge.schemas import RecordsView
from app.models.fees import FeeLineItem
from app.models.records_evidence import RequestEvidenceNote, RequestExemptionDecision
from app.models.request_workflow import RequestMessage, RequestPublicStatus, RequestTimeline
from app.models.search import SearchQuery, SearchResult
from app.models.document import Document
from app.models.request import RequestDocument
from app.models.records_files import RequestFileEvidence, RequestReleaseCopy
from app.models.records_artifacts import RequestArtifact
from app.models.records_artifacts import RequestPublication
from app.models.notifications import NotificationLog
from app.models.audit import AuditLog
from app.models.request import RecordsRequest
from app.desktop_bridge.schemas import RecordsStateRead


def epoch(value):
    return int(value.timestamp()) if value is not None else None


async def records_state(session):
    requests = (await session.execute(select(RecordsRequest).order_by(
        RecordsRequest.created_at.desc(), RecordsRequest.id
    ))).scalars().all()
    ids = {req.id: req.desktop_id or f"records-{req.id}" for req in requests}
    notifications = (await session.execute(select(NotificationLog).where(
        NotificationLog.module_id == "civicrecords-ai"
    ).order_by(NotificationLog.created_at.desc(), NotificationLog.id))).scalars().all()
    publications = (await session.execute(select(RequestPublication).order_by(RequestPublication.created_at.desc()))).scalars().all()
    audit = (await session.execute(select(AuditLog).where(AuditLog.resource_type == "request")
                                  .order_by(AuditLog.id.desc()))).scalars().all()
    return RecordsStateRead(
        records_requests=[await request_view(session, req) for req in requests],
        notification_events=[dict(id=legacy_id(row, "notification"), notification_id=str(row.id),
                                  module_id=row.module_id, record_id=ids.get(row.request_id, ""),
                                  audience=row.audience or "", channel=row.channel, subject=row.subject or "",
                                  body=row.body or "", status=row.status, created_at_unix_seconds=epoch(row.created_at),
                                  sent_at_unix_seconds=epoch(row.sent_at)) for row in notifications],
        publication_events=[dict(id=legacy_id(row, "publication"), source_module="civicrecords-ai",
                                 source_record_id=ids.get(row.request_id, ""), record_type="records-response",
                                 public_payload=row.payload, payload_hash=row.payload_hash,
                                 published_at_unix_seconds=epoch(row.created_at)) for row in publications],
        audit_entries=[dict(id=f"sql-audit-{row.id}", module_id="civicrecords-ai" if row.resource_type == "request" else "civiccore",
                            action=row.action, summary=str((row.details or {}).get("note", row.action)),
                            created_at_unix_seconds=epoch(row.timestamp), previous_hash=row.prev_hash,
                            entry_hash=row.entry_hash) for row in audit],
    )


def legacy_id(row, prefix):
    return row.legacy_id if row.legacy_id is not None else f"{prefix}-{row.id}"


async def ordered_rows(session, model, request_id):
    return (await session.execute(select(model).where(model.request_id == request_id).order_by(
        model.position.asc().nulls_last(), model.created_at.asc(), model.id.asc()
    ))).scalars().all()


async def request_view(session, req):
    notes = defaultdict(list)
    for row in await ordered_rows(session, RequestEvidenceNote, req.id):
        notes[row.kind].append(row.content)
    receipts = []
    for row in await ordered_rows(session, SearchQuery, req.id):
        results = (await session.execute(select(SearchResult).where(
            SearchResult.query_id == row.id
        ).order_by(SearchResult.rank, SearchResult.id))).scalars().all()
        receipts.append({
            "id": legacy_id(row, "records-search-session"), "query": row.query_text,
            "locations": row.locations or "", "reviewer": row.reviewer_label or "",
            "created_at_unix_seconds": epoch(row.created_at),
            "results": [{"id": legacy_id(result, "records-search-result"),
                         "title": result.title or "", "citation": result.citation or "",
                         "summary": result.summary or "", "status": result.review_status or ""}
                        for result in results],
        })
    documents = []
    for evidence in await ordered_rows(session, RequestFileEvidence, req.id):
        link = await session.get(RequestDocument, evidence.id)
        document = await session.get(Document, link.document_id)
        copy = await session.scalar(select(RequestReleaseCopy).where(
            RequestReleaseCopy.attachment_id == evidence.id
        ).order_by(RequestReleaseCopy.position.desc()).limit(1))
        item = dict(id=legacy_id(evidence, "records-document"), attachment_id=str(evidence.id),
                    title=evidence.title, original_path=evidence.original_path, stored_path=document.source_path,
                    citation=evidence.citation, sha256=document.file_hash, size_bytes=document.file_size,
                    status=f"{copy.status} attached" if copy else "attached for response review",
                    added_by=evidence.added_by, created_at_unix_seconds=epoch(evidence.created_at))
        if copy:
            item.update(release_original_path=copy.original_path, release_stored_path=copy.stored_path,
                        release_file_name=copy.file_name, release_sha256=copy.sha256,
                        release_size_bytes=copy.size_bytes, release_status=copy.status, release_note=copy.note,
                        release_added_by=copy.added_by, release_added_at_unix_seconds=epoch(copy.created_at))
        documents.append(item)
    artifacts = (await session.execute(select(RequestArtifact).where(
        RequestArtifact.request_id == req.id, RequestArtifact.completed_at.is_not(None)
    ).order_by(RequestArtifact.completed_at, RequestArtifact.id))).scalars().all()
    return RecordsView(
        release_packages=[dict(id=legacy_id(row, "records-release-package"), export_path=row.export_path,
                               package_hash=row.sha256, created_at_unix_seconds=epoch(row.completed_at),
                               **{key: getattr(row, key) for key in ("document_count", "release_artifact_count",
                                  "search_session_count", "release_count", "redacted_count", "exempt_count")})
                          for row in artifacts if row.kind == "release-package"],
        documents=documents,
        request_id=str(req.id),
        id=req.desktop_id or f"records-{req.id}", public_tracking_number=req.public_tracking_number or "",
        requester=req.requester_name, requester_contact=req.requester_contact, submitted_via=req.submitted_via,
        summary=req.description, deadline=req.deadline_label, deadline_basis=req.deadline_basis,
        status=req.display_status or req.status.value, assigned_to=req.assigned_label,
        clarification_notes=notes["clarification"], search_notes=notes["search"], search_sessions=receipts,
        exemption_reviews=notes["exemption"], citations=notes["citation"],
        approval_notes=notes["approval"], exports=notes["export"] + [row.export_path for row in artifacts if row.kind == "response"], response_draft=req.response_draft or "",
        fee_estimate=req.fee_estimate_text, fee_waiver_reason=req.fee_waiver_reason,
        fee_line_items=[{"id": legacy_id(row, "records-fee-line"), "description": row.description,
                         "schedule_basis": row.schedule_basis, "amount_cents": int(row.total * 100),
                         "created_at_unix_seconds": epoch(row.created_at)}
                        for row in await ordered_rows(session, FeeLineItem, req.id)],
        exemption_decisions=[{"id": legacy_id(row, "records-exemption-decision"), "source": row.source,
                              "kind": row.kind, "finding": row.finding, "decision": row.decision,
                              "basis": row.basis, "reviewer": row.reviewer_label,
                              "created_at_unix_seconds": epoch(row.created_at)}
                             for row in await ordered_rows(session, RequestExemptionDecision, req.id)],
        timeline=[{"id": legacy_id(row, "records-timeline"), "action": row.event_type,
                   "actor": row.actor_label if row.actor_label is not None else (row.actor_role or ""),
                   "note": row.description, "created_at_unix_seconds": epoch(row.created_at)}
                  for row in await ordered_rows(session, RequestTimeline, req.id)],
        public_status_events=[{"id": legacy_id(row, "records-public-status"), "label": row.label,
                               "summary": row.summary, "status": row.status,
                               "created_at_unix_seconds": epoch(row.created_at)}
                              for row in await ordered_rows(session, RequestPublicStatus, req.id)],
        messages=[{"id": legacy_id(row, "records-message"), "author": row.sender_label or row.sender_type,
                   "author_role": row.sender_type, "body": row.message_text,
                   "visibility": "internal" if row.is_internal else "requester thread",
                   "created_at_unix_seconds": epoch(row.created_at)}
                  for row in await ordered_rows(session, RequestMessage, req.id)],
        deadline_reviewed_at_unix_seconds=epoch(req.deadline_reviewed_at),
        approved_at_unix_seconds=epoch(req.approved_at), fulfilled_at_unix_seconds=epoch(req.fulfilled_at),
        closed_at_unix_seconds=epoch(req.closed_at), created_at_unix_seconds=epoch(req.created_at),
    )
