"""Read-only translation of canonical Records rows into the accepted view."""

from collections import defaultdict

from sqlalchemy import select

from app.desktop_bridge.schemas import RecordsView
from app.models.fees import FeeLineItem
from app.models.records_evidence import RequestEvidenceNote, RequestExemptionDecision
from app.models.request_workflow import RequestMessage, RequestPublicStatus, RequestTimeline
from app.models.search import SearchQuery, SearchResult


def epoch(value):
    return int(value.timestamp()) if value is not None else None


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
    return RecordsView(
        id=req.desktop_id or f"records-{req.id}", public_tracking_number=req.public_tracking_number or "",
        requester=req.requester_name, requester_contact=req.requester_contact, submitted_via=req.submitted_via,
        summary=req.description, deadline=req.deadline_label, deadline_basis=req.deadline_basis,
        status=req.display_status or req.status.value, assigned_to=req.assigned_label,
        clarification_notes=notes["clarification"], search_notes=notes["search"], search_sessions=receipts,
        exemption_reviews=notes["exemption"], citations=notes["citation"],
        approval_notes=notes["approval"], exports=notes["export"], response_draft=req.response_draft or "",
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
