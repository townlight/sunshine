"""Accepted local walk-up Records behavior, separate from authenticated web portal."""
from datetime import datetime, timezone
import hmac
from sqlalchemy import Sequence, select

from app.audit.logger import write_audit_log
from app.desktop_bridge.projection import request_view
from app.models.request import RecordsRequest
from app.models.request_workflow import RequestMessage, RequestPublicStatus, RequestTimeline
from app.notifications.service import queue_local_notification
from app.requests import service, workflow


def public_view(view, *, include_thread=False):
    updates = {key: [] for key in ("clarification_notes", "search_notes", "search_sessions", "exemption_reviews",
                                  "exemption_decisions", "fee_line_items", "approval_notes", "release_packages",
                                  "timeline", "documents")}
    updates.update({key: "" for key in ("requester_contact", "assigned_to", "fee_estimate", "fee_waiver_reason", "response_draft")})
    updates["messages"] = [m for m in view.messages if m.visibility == "requester thread"] if include_thread else []
    return view.model_copy(update=updates)


async def public_state(session, matched=None):
    released = (await session.execute(select(RecordsRequest).where(
        RecordsRequest.fulfilled_at.is_not(None)
    ).order_by(RecordsRequest.created_at.desc(), RecordsRequest.id))).scalars().all()
    views = [public_view(await request_view(session, req)) for req in released]
    # Preserve rc.3: released status view takes precedence over matched thread.
    if matched is not None and not any(view.request_id == str(matched.id) for view in views):
        views.insert(0, public_view(await request_view(session, matched), include_thread=True))
    return views


def ascii_lower(value):
    return value.translate(str.maketrans("ABCDEFGHIJKLMNOPQRSTUVWXYZ", "abcdefghijklmnopqrstuvwxyz"))


async def find_request(session, tracking, contact, *, lock=False):
    # Tracking is generated ASCII; contact matching preserves accepted semantics.
    stmt = select(RecordsRequest).where(RecordsRequest.public_tracking_number == tracking.strip().upper())
    if lock:
        stmt = stmt.with_for_update()
    req = await session.scalar(stmt)
    if req and hmac.compare_digest(ascii_lower(req.requester_contact).encode(), ascii_lower(contact.strip()).encode()):
        return req
    return None


async def submit(session, data):
    req = await service.create_records_request(
        session, service.RequestIntake(requester_name=data.requester, description=data.summary), actor=None,
        assigned_to=None, department_id=None, audit_action="submit-public-records-request", native_role="resident/public",
    )
    number = await session.scalar(select(Sequence("records_public_tracking_seq").next_value()))
    tracking = f"REQ-{number:04d}"
    req.desktop_id = f"records-{req.id}"
    req.public_tracking_number = tracking
    req.requester_contact = data.requesterContact
    req.submitted_via = "Resident/Public local intake"
    req.deadline_label = data.deadline or "Pending clerk deadline review"
    req.display_status = "public intake received"
    now = datetime.now(timezone.utc)
    session.add(RequestTimeline(request_id=req.id, event_type="public intake", actor_id=None,
                               actor_role="resident/public", actor_label="resident/public", position=1,
                               description=f"Public request {tracking} received for staff review.", created_at=now))
    session.add(RequestPublicStatus(request_id=req.id, label="Request received", status=req.display_status,
                                   summary=f"Request {tracking} was received locally and is waiting for staff deadline review.",
                                   created_at=now, position=1))
    for audience, subject, body in (
        ("records staff", f"New public records request {tracking}",
         f"{data.requester} submitted request {tracking}. Review the deadline, scope, assignment, and contact path in the local Records workflow."),
        ("requester", f"Records request {tracking} received",
         f"Request {tracking} was received locally. Staff will review the deadline and response path. Contact on file: {data.requesterContact}."),
    ):
        await queue_local_notification(session, request_id=req.id, module_id="civicrecords-ai", audience=audience,
                                       subject=subject, body=body, created_at=now)
    await session.flush()
    return req


async def add_message(session, req, body):
    workflow.ensure_active(req)
    now = datetime.now(timezone.utc)
    req.display_status = "requester message received"
    session.add(RequestMessage(request_id=req.id, sender_type="requester", sender_id=None,
                               sender_label=req.requester_name, message_text=body, is_internal=False,
                               position=await workflow.next_position(session, RequestMessage, req.id)))
    session.add(RequestTimeline(request_id=req.id, event_type="requester message received", actor_id=None,
                               actor_role="resident/public", actor_label="resident/public", description=body,
                               created_at=now, position=await workflow.next_position(session, RequestTimeline, req.id)))
    session.add(RequestPublicStatus(request_id=req.id, label="Requester message received", status=req.display_status,
                                   summary="A requester message was added to the local request thread.", created_at=now,
                                   position=await workflow.next_position(session, RequestPublicStatus, req.id)))
    await queue_local_notification(session, request_id=req.id, module_id="civicrecords-ai", audience="records staff",
                                   subject=f"Records request {req.public_tracking_number} requester message",
                                   body=f"{req.requester_name} sent a message on request {req.public_tracking_number}: {body}", created_at=now)
    await write_audit_log(session=session, action="add-public-records-message", resource_type="request",
                          resource_id=str(req.id), user_id=None, details={"native_role": "resident/public"}, commit=False)
    await session.flush()
