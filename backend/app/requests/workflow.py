"""Records lifecycle services over the shared Records schema.

Compatibility evidence is explicit and typed. Transactions, authentication and
native file operations belong to their callers, never to a second state store.
"""

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import hashlib

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.logger import write_audit_log
from app.models.fees import FeeLineItem, FeeWaiver
from app.models.records_evidence import RequestEvidenceNote, RequestExemptionDecision
from app.models.request import RecordsRequest, RequestStatus
from app.models.request_workflow import RequestMessage, RequestPublicStatus, RequestTimeline
from app.models.search import SearchQuery, SearchResult, SearchSession
from app.models.user import User
from app.notifications.service import queue_local_notification


@dataclass(frozen=True)
class RecordsActor:
    user: User
    role: str


def ensure_active(req: RecordsRequest):
    if req.closed_at is not None or req.status == RequestStatus.CLOSED:
        raise ValueError("This records request is closed. Create a new request for new records work.")
    if req.fulfilled_at is not None or req.status == RequestStatus.FULFILLED:
        raise ValueError("This records request has already been fulfilled. Close it or create a new request.")


def replace_response_text(req: RecordsRequest, text: str):
    """The accepted narrow rule; unrelated edits never call this function."""
    if (req.response_draft or "") != text:
        req.approved_at = None
        req.approved_response_sha256 = None
    req.response_draft = text


def stamp_response_approval(req: RecordsRequest, when: datetime):
    # Eligibility and authorization remain at each existing product boundary.
    req.approved_at = when
    req.approved_response_sha256 = hashlib.sha256((req.response_draft or "").encode()).hexdigest()
    req.status = RequestStatus.APPROVED


async def next_position(session, model, request_id, *conditions):
    return 1 + (await session.scalar(select(func.count()).select_from(model).where(
        model.request_id == request_id, *conditions
    )) or 0)


async def add_note(session, req, actor, kind, content, *, unique=False):
    if unique and await session.scalar(select(RequestEvidenceNote.id).where(
        RequestEvidenceNote.request_id == req.id, RequestEvidenceNote.kind == kind,
        RequestEvidenceNote.content == content,
    ).limit(1)):
        return
    session.add(RequestEvidenceNote(
        request_id=req.id, kind=kind, content=content, actor_id=actor.user.id,
        position=await next_position(session, RequestEvidenceNote, req.id, RequestEvidenceNote.kind == kind),
    ))
    await session.flush()


async def record_progress(
    session, req, actor, *, action, status, canonical_status, timeline_action,
    timeline_note, public_label, public_summary, audit_note, timeline_actor="records staff",
    notification=None,
):
    now = datetime.now(timezone.utc)
    req.display_status = status
    req.status = canonical_status
    session.add(RequestTimeline(
        request_id=req.id, event_type=timeline_action, actor_id=actor.user.id,
        actor_role=actor.role, actor_label=timeline_actor, description=timeline_note,
        created_at=now, position=await next_position(session, RequestTimeline, req.id),
    ))
    session.add(RequestPublicStatus(
        request_id=req.id, label=public_label, summary=public_summary, status=status,
        created_at=now, position=await next_position(session, RequestPublicStatus, req.id),
    ))
    if notification is not None:
        audience, subject, body = notification
        await queue_local_notification(
            session, request_id=req.id, module_id="civicrecords-ai", audience=audience,
            subject=subject, body=body, created_at=now,
        )
    await write_audit_log(
        session=session, action=action, resource_type="request", resource_id=str(req.id),
        user_id=actor.user.id, details={"native_role": actor.role, "note": audit_note},
        commit=False,
    )
    await session.flush()


async def assign_request(session, req, actor, *, assigned_to):
    req.assigned_label = assigned_to
    await record_progress(
        session, req, actor, action="assign-records-request", status="assigned",
        canonical_status=RequestStatus.ASSIGNED, timeline_action="assigned",
        timeline_note=f"Assigned to {assigned_to}.", public_label="Staff review assigned",
        public_summary="The request was assigned for staff review.",
        audit_note=f"Assigned records request to: {assigned_to}",
    )
    return "Records request assigned for staff search and review."


async def set_deadline(session, req, actor, *, deadline, basis, calculation=None):
    req.deadline_label = deadline
    req.deadline_basis = basis
    req.statutory_deadline = datetime.combine(date.fromisoformat(deadline), time(), timezone.utc)
    req.deadline_reviewed_at = datetime.now(timezone.utc)
    tracking = req.public_tracking_number or req.desktop_id or str(req.id)
    calculated = calculation is not None
    verb = "calculated" if calculated else "reviewed"
    await record_progress(
        session, req, actor,
        action="calculate-records-deadline" if calculated else "set-records-deadline",
        status=f"deadline {verb}", canonical_status=RequestStatus.RECEIVED,
        timeline_action=f"deadline {verb}",
        timeline_note=(f"{calculation[0]}: received {calculation[1]}; due {deadline}. {basis}" if calculated
                       else f"Response deadline set to {deadline}; basis: {basis}."),
        public_label=f"Deadline {verb}",
        public_summary=(f"Staff calculated the response deadline as {deadline}." if calculated else
                        f"Staff reviewed the response deadline: {deadline}. Basis: {basis}."),
        audit_note=(f"Records request {tracking} deadline calculated as {deadline}: {basis}" if calculated
                    else f"Records request {tracking} deadline set to {deadline}; basis: {basis}"),
        notification=("requester", f"Records request {tracking} deadline {verb}",
                      f"Staff {verb} the response deadline for {req.requester_name}: {deadline}. Basis: {basis}{'' if calculated else '.'}"),
    )
    return (f"Records deadline calculated as {deadline} and saved locally with basis evidence." if calculated
            else "Records deadline reviewed and saved locally with basis evidence.")


async def calculate_deadline(session, req, actor, *, received_date, rule_name, day_count, day_type, basis):
    current = date.fromisoformat(received_date)
    business = day_type.lower() in {"business", "business day", "business days", "working", "working days"}
    added = 0
    while added < day_count:
        current += timedelta(days=1)
        if business and current.weekday() >= 5:
            continue
        added += 1
    normalized = "business days" if business else "calendar days"
    calculation_basis = (
        f"{basis} Rule: {rule_name}; received {received_date}; calculated as {day_count} {normalized} "
        f"from receipt; weekends {'are' if business else 'are not'} automatically skipped; "
        "city/state holidays must be checked by staff."
    )
    return await set_deadline(session, req, actor, deadline=current.isoformat(), basis=calculation_basis,
                              calculation=(rule_name, received_date))


async def request_clarification(session, req, actor, *, note):
    await add_note(session, req, actor, "clarification", note)
    tracking = req.public_tracking_number or req.desktop_id or str(req.id)
    await record_progress(
        session, req, actor, action="request-records-clarification", status="clarification",
        canonical_status=RequestStatus.CLARIFICATION_NEEDED, timeline_action="clarification requested",
        timeline_note=note, public_label="Clarification requested",
        public_summary="Staff requested clarification before completing the records review.",
        audit_note="Saved clarification note for records request.",
        notification=("requester", f"Records request {tracking} needs clarification",
                      f"Staff requested clarification before completing the records search: {note}"),
    )
    return "Clarification note saved; no denial or release occurred."


async def add_staff_message(session, req, actor, *, body):
    session.add(RequestMessage(
        request_id=req.id, sender_type="staff", sender_id=actor.user.id, sender_label="Records staff",
        message_text=body, is_internal=False, position=await next_position(session, RequestMessage, req.id),
    ))
    tracking = req.public_tracking_number or req.desktop_id or str(req.id)
    await record_progress(
        session, req, actor, action="add-records-message", status="message sent",
        canonical_status=RequestStatus.RECEIVED, timeline_action="message sent", timeline_note=body,
        public_label="Message added",
        public_summary="Records staff added a requester-visible message to this request.",
        audit_note=f"Added requester-visible message for records request {tracking}.",
        notification=("requester", f"Records request {tracking} message", body),
    )
    return "Requester-visible records message saved and queued in the local notification log."


async def record_search_note(session, req, actor, *, note, citation):
    await add_note(session, req, actor, "search", note)
    if citation:
        await add_note(session, req, actor, "citation", citation)
    await record_progress(
        session, req, actor, action="record-records-search", status="searching",
        canonical_status=RequestStatus.SEARCHING, timeline_action="search recorded",
        timeline_note=note + (f" Citation: {citation}." if citation else ""),
        public_label="Records search in progress", public_summary="Staff recorded progress on the records search.",
        audit_note="Recorded records search source note.",
    )
    return "Search source note saved with citation evidence."


async def record_search_receipt(session, req, actor, *, query, locations, title, citation, summary, status, reviewer):
    search = SearchSession(user_id=actor.user.id)
    session.add(search)
    await session.flush()
    receipt = SearchQuery(
        session_id=search.id, request_id=req.id, query_text=query, results_count=1,
        position=await next_position(session, SearchQuery, req.id), locations=locations,
        reviewer_label=reviewer or "records staff",
    )
    session.add(receipt)
    await session.flush()
    session.add(SearchResult(
        query_id=receipt.id, rank=1, chunk_id=None, similarity_score=None,
        title=title, citation=citation, summary=summary, review_status=status or "responsive",
    ))
    await add_note(session, req, actor, "citation", citation, unique=True)
    await record_progress(
        session, req, actor, action="record-records-search-session", status="search session recorded",
        canonical_status=RequestStatus.SEARCHING, timeline_action="search session recorded",
        timeline_note=f"{query} across {locations}; result {title}.", public_label="Records search updated",
        public_summary="Staff saved structured search progress for this request.",
        audit_note=f"Recorded records search session {query} with result {citation}.",
    )
    return "Records search session saved with source-result evidence."


async def record_exemption_note(session, req, actor, *, note):
    await add_note(session, req, actor, "exemption", note)
    await record_progress(
        session, req, actor, action="add-records-exemption-review", status="in review",
        canonical_status=RequestStatus.IN_REVIEW, timeline_action="exemption review recorded", timeline_note=note,
        public_label="Review in progress", public_summary="Staff recorded review progress before final response approval.",
        audit_note="Recorded human exemption review note.",
    )
    return "Exemption review note saved for human approval."


async def record_exemption_decision(session, req, actor, *, source, kind, finding, decision, basis, reviewer):
    session.add(RequestExemptionDecision(
        request_id=req.id, position=await next_position(session, RequestExemptionDecision, req.id),
        source=source, kind=kind, finding=finding, decision=decision, basis=basis,
        reviewer_label=reviewer or "records staff", actor_id=actor.user.id,
    ))
    await add_note(session, req, actor, "citation", basis, unique=True)
    await record_progress(
        session, req, actor, action="add-records-exemption-decision", status="exemption decision recorded",
        canonical_status=RequestStatus.IN_REVIEW, timeline_action="exemption decision recorded",
        timeline_note=f"{decision} decision for {source}: {finding} under {basis}.",
        public_label="Release review updated", public_summary="Staff recorded release, redaction, or exemption review progress.",
        audit_note=f"Recorded {decision} exemption decision for {source} under {basis}.",
    )
    return "Structured exemption decision saved with source evidence."


async def estimate_fee(session, req, actor, *, estimate):
    req.fee_estimate_text = estimate
    await record_progress(
        session, req, actor, action="estimate-records-fee", status="ready",
        canonical_status=RequestStatus.READY_FOR_RELEASE, timeline_action="fee estimate saved", timeline_note=estimate,
        public_label="Fee review updated", public_summary="Staff updated the request fee review.",
        audit_note=f"Saved records fee estimate: {estimate}",
    )
    return "Fee estimate saved before approval or fulfillment."


async def add_fee_line(session, req, actor, *, description, basis, amount):
    value = Decimal(amount)
    item = FeeLineItem(
        request_id=req.id, description=description, schedule_basis=basis, quantity=1,
        unit_price=value, total=value, position=await next_position(session, FeeLineItem, req.id),
    )
    session.add(item)
    await session.flush()
    total, count = (await session.execute(select(func.sum(FeeLineItem.total), func.count()).where(
        FeeLineItem.request_id == req.id
    ))).one()
    req.estimated_fee = total
    req.fee_status = "waived" if req.fee_waiver_reason else "estimated"
    req.fee_estimate_text = (f"$0.00 waived: {req.fee_waiver_reason}" if req.fee_waiver_reason
                             else f"${total:.2f} estimated from {count} fee line item(s).")
    await record_progress(
        session, req, actor, action="add-records-fee-line", status="fee review",
        canonical_status=RequestStatus.IN_REVIEW, timeline_action="fee line added",
        timeline_note=f"{description}: ${value:.2f} under {basis}", public_label="Fee review updated",
        public_summary="Staff updated the request fee review.",
        audit_note=f"Added records fee line: {description} ${value:.2f} under {basis}",
    )
    return "Records fee line item saved with local evidence."


async def waive_fee(session, req, actor, *, reason):
    req.fee_waiver_reason = reason
    req.fee_estimate_text = f"$0.00 waived: {reason}"
    req.fee_status = "waived"
    session.add(FeeWaiver(
        request_id=req.id, waiver_type="other", reason=reason, status="approved",
        requested_by=actor.user.id, reviewed_by=actor.user.id, reviewed_at=datetime.now(timezone.utc),
    ))
    await record_progress(
        session, req, actor, action="waive-records-fee", status="fee waived",
        canonical_status=RequestStatus.IN_REVIEW, timeline_action="fee waived", timeline_note=reason,
        public_label="Fee waived", public_summary="Staff marked the records fee as waived.",
        audit_note=f"Recorded records fee waiver: {reason}",
    )
    return "Records fee waiver saved with local evidence."


async def save_response_draft(session, req, actor, *, text, citation):
    replace_response_text(req, text)
    if citation:
        await add_note(session, req, actor, "citation", citation)
    await record_progress(
        session, req, actor, action="draft-records-response", status="drafted",
        canonical_status=RequestStatus.DRAFTED, timeline_action="response drafted",
        timeline_note=f"Draft response saved with citation {citation}." if citation else "Draft response saved.",
        public_label="Response drafting", public_summary="Staff saved a response draft for review.",
        audit_note="Drafted records response with local citation evidence.",
    )
    return "Records response draft saved with citation evidence."


async def approve_response(session, req, actor, *, note):
    if not (req.response_draft or "").strip():
        raise ValueError("Draft a records response before approval.")
    if not await session.scalar(select(RequestEvidenceNote.id).where(
        RequestEvidenceNote.request_id == req.id, RequestEvidenceNote.kind == "citation"
    ).limit(1)):
        raise ValueError("Add at least one citation or source note before approval.")
    if note:
        await add_note(session, req, actor, "approval", note)
    stamp_response_approval(req, datetime.now(timezone.utc))
    await record_progress(
        session, req, actor, action="approve-records-response", status="approved",
        canonical_status=RequestStatus.APPROVED, timeline_action="response approved",
        timeline_note=note or "Response approved by a human reviewer.", public_label="Response approved",
        public_summary="A human reviewer approved the response for export.",
        audit_note="Approved records response for export by a human reviewer.",
    )
    return "Records response approved by staff; export is now available."
