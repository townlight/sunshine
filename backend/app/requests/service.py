"""Shared Records operations; callers own their database transaction."""

from dataclasses import dataclass
from datetime import datetime, timezone
import uuid

from sqlalchemy import Sequence, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.audit.logger import write_audit_log
from app.models.city_profile import CityProfile
from app.models.request import RecordsRequest
from app.models.request_workflow import RequestPublicStatus, RequestTimeline
from app.models.user import User
from app.notifications.service import queue_local_notification, queue_notification


@dataclass(frozen=True)
class RequestIntake:
    requester_name: str
    description: str
    requester_email: str | None = None
    requester_phone: str | None = None
    requester_type: str | None = None
    statutory_deadline: datetime | None = None
    priority: str = "normal"
    scope_assessment: str | None = None
    department_id: uuid.UUID | None = None


async def create_records_request(
    session: AsyncSession,
    data: RequestIntake,
    *,
    actor: User | None,
    assigned_to: uuid.UUID | None,
    department_id: uuid.UUID | None,
    audit_action: str = "create_request",
    native_role: str | None = None,
) -> RecordsRequest:
    """One intake implementation for web and native callers.

    Authorization stays at each authenticated boundary. Assignment is an
    explicit input: web retains creator-assignment; native retains its
    unassigned intake. No internal commit may split request/outbox/audit.
    """
    req = RecordsRequest(
        requester_name=data.requester_name, requester_email=data.requester_email,
        requester_phone=data.requester_phone, requester_type=data.requester_type,
        description=data.description, statutory_deadline=data.statutory_deadline,
        scope_assessment=data.scope_assessment, priority=data.priority,
        created_by=actor.id if actor else None, assigned_to=assigned_to, department_id=department_id,
    )
    session.add(req)
    await session.flush()
    if req.requester_email:
        profile = (await session.execute(select(CityProfile).limit(1))).scalar_one_or_none()
        await queue_notification(
            session=session, event_type="request_received",
            recipient_email=req.requester_email, request_id=req.id,
            context_data={
                "requester_name": req.requester_name, "request_id": str(req.id),
                "status": req.status.value,
                "city_name": profile.city_name if profile else "Records Office",
            },
        )
    await write_audit_log(
        session=session, action=audit_action, resource_type="request",
        resource_id=str(req.id), user_id=actor.id if actor else None,
        details={"requester": data.requester_name, "description": data.description[:100],
                 **({"native_role": native_role} if native_role is not None else {})},
        commit=False,
    )
    return req


async def create_native_records_request(
    session: AsyncSession, data: RequestIntake, *, actor: User,
    native_role: str, deadline_label: str, deadline_basis: str,
) -> RecordsRequest:
    """Preserve accepted native intake evidence using the same Records row."""
    req = await create_records_request(
        session, data, actor=actor, assigned_to=None, department_id=actor.department_id,
        audit_action="create-records-request", native_role=native_role,
    )
    number = await session.scalar(select(Sequence("records_public_tracking_seq").next_value()))
    tracking = f"REQ-{number:04d}"
    now = datetime.now(timezone.utc)
    req.desktop_id = f"records-{req.id}"
    req.public_tracking_number = tracking
    req.submitted_via = "Staff intake"
    req.deadline_label = deadline_label
    req.deadline_basis = deadline_basis or "Staff-entered deadline at intake."
    req.deadline_reviewed_at = now
    req.display_status = "received"
    session.add(RequestTimeline(
        request_id=req.id, event_type="intake", actor_id=actor.id,
        actor_role=native_role, actor_label="records staff",
        description=f"Staff created request {tracking} with deadline {deadline_label}.",
        created_at=now, position=1,
    ))
    session.add(RequestPublicStatus(
        request_id=req.id, label="Request received", status="received",
        summary=f"Request {tracking} was created by staff and is being tracked locally.",
        created_at=now, position=1,
    ))
    await queue_local_notification(
        session, request_id=req.id, module_id="civicrecords-ai", audience="records staff",
        subject=f"Records request {tracking} created",
        body=f"Staff-created request for {data.requester_name} is saved locally with deadline {deadline_label}.",
        created_at=now,
    )
    await session.flush()
    return req
