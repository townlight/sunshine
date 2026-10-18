"""Native authentication/translation only; Records owns the domain operation."""

from datetime import date, datetime, time, timezone
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.desktop_session import validate_native_session
from app.database import get_async_session
from app.desktop_bridge.schemas import NativeRequestRead, RecordsCommand, RecordsOperationRead, RecordsStateRead, RecordsView, StaffRecordsIntake
from app.desktop_bridge.projection import request_view, records_state
from app.models.notifications import NotificationLog
from app.audit.logger import write_audit_log
from app.desktop_bridge.records import apply_command
from app.models.request import RecordsRequest
from app.models.user import User, UserRole
from app.requests import service
from app.requests.workflow import RecordsActor
from app.requests import files
from app.desktop_bridge.schemas import AttachDocument, AttachReleaseCopy
from app.desktop_bridge.schemas import PrepareArtifact, ArtifactPlan, CompleteArtifact
from app.requests import artifacts
from app.requests import native_public
from app.auth.desktop_session import validate_native_public_proof
from app.desktop_bridge.schemas import PublicIntake, PublicLookup, PublicMessage
from app.desktop_bridge.schemas import GeneratedDraft
from app.requests import workflow

router = APIRouter(prefix="/desktop/v1", tags=["native-desktop"])


def native_public_shell(request: Request, proof: str | None = Header(default=None, alias="X-Townlight-Public")):
    try:
        validate_native_public_proof(proof, profile_root=request.app.state.desktop_profile_root)
    except PermissionError as error:
        raise HTTPException(401, str(error)) from None
    if "civicrecords-ai" not in request.app.state.desktop_enabled_modules:
        raise HTTPException(403, "Records is not enabled in this profile.")
    if not request.app.state.desktop_domain_enabled:
        raise HTTPException(503, "Records migration is not activated; no work was accepted.")


@router.get("/public/records-state", dependencies=[Depends(native_public_shell)], response_model=RecordsStateRead)
async def public_records_state(request: Request, session: AsyncSession = Depends(get_async_session)):
    return RecordsStateRead(records_requests=await native_public.public_state(session), demo_fixture=await demo_marker(request, session))


async def demo_marker(request, session):
    loader = getattr(request.app.state, "desktop_demo_marker", None)
    return await loader(session) if loader is not None else None


@router.post("/public/requests", dependencies=[Depends(native_public_shell)])
async def public_records_intake(data: PublicIntake, request: Request, session: AsyncSession = Depends(get_async_session)):
    req = await native_public.submit(session, data)
    result = {"accepted": True, "message": f"Public records request {req.public_tracking_number} received.",
              "state": RecordsStateRead(records_requests=await native_public.public_state(session, req), demo_fixture=await demo_marker(request, session))}
    await session.commit()
    return result


@router.post("/public/lookup", dependencies=[Depends(native_public_shell)])
async def public_records_lookup(data: PublicLookup, request: Request, session: AsyncSession = Depends(get_async_session)):
    req = await native_public.find_request(session, data.trackingNumber, data.requesterContact)
    return {"accepted": req is not None, "message": "Status found" if req else "No local request matched that request number and submitted contact.",
            "state": RecordsStateRead(records_requests=await native_public.public_state(session, req), demo_fixture=await demo_marker(request, session))}


@router.post("/public/messages", dependencies=[Depends(native_public_shell)])
async def public_records_message(data: PublicMessage, request: Request, session: AsyncSession = Depends(get_async_session)):
    req = await native_public.find_request(session, data.trackingNumber, data.requesterContact, lock=True)
    if req is not None:
        try:
            await native_public.add_message(session, req, data.publicRequestMessage)
        except ValueError as error:
            await session.rollback()
            raise HTTPException(400, str(error)) from None
    result = {"accepted": req is not None, "message": "Requester message saved." if req else "No local request matched that request number and submitted contact.",
              "state": RecordsStateRead(records_requests=await native_public.public_state(session, req), demo_fixture=await demo_marker(request, session))}
    await session.commit()
    return result


async def file_operation(session, req, actor, role, action, data, profile_root, attachment_id=None):
    if req is None:
        raise HTTPException(404, "Records request not found.")
    try:
        principal = RecordsActor(actor, role)
        if attachment_id is None:
            message = await files.attach_document(session, req, principal, data, profile_root)
        else:
            message = await files.attach_release_copy(session, req, principal, attachment_id, data, profile_root)
        result = RecordsOperationRead(action=action, message=message, request=await request_view(session, req))
        await session.commit()
        return result
    except ValueError as error:
        await session.rollback()
        raise HTTPException(400, str(error)) from None


async def native_records_user(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    proof: str | None = Header(default=None, alias="X-Townlight-Session"),
) -> User:
    from app.auth.native_identity import mapped_native_actor
    return await mapped_native_actor(request, session, proof, "civicrecords-ai")


@router.get("/records-state", response_model=RecordsStateRead)
async def get_native_records_state(
    session: AsyncSession = Depends(get_async_session),
    actor: User = Depends(native_records_user),
):
    # Same native capability boundary as individual readback; no JSON merge.
    return await records_state(session)


@router.post("/notifications/{notification_id}/sent", response_model=RecordsStateRead)
async def mark_native_notification_sent(
    notification_id: uuid.UUID, request: Request,
    session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    item = await session.get(NotificationLog, notification_id, with_for_update=True)
    if item is None or item.module_id != "civicrecords-ai":
        raise HTTPException(404, "Records notification not found.")
    if item.sent_at is not None:
        raise HTTPException(400, "This local notification is already marked sent.")
    item.status = "sent / logged"
    item.sent_at = datetime.now(timezone.utc)
    await write_audit_log(session=session, action="mark-notification-sent", resource_type="request",
                          resource_id=str(item.request_id), user_id=actor.id,
                          details={"native_role": request.state.native_role, "note": f"Marked local notification sent: {item.subject}"}, commit=False)
    result = await records_state(session)
    await session.commit()
    return result


@router.post("/requests/{request_id}/documents", response_model=RecordsOperationRead)
async def attach_native_document(
    request_id: uuid.UUID, data: AttachDocument, request: Request,
    session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    return await file_operation(session, req, actor, request.state.native_role,
                                "add-records-document", data, request.app.state.desktop_profile_root)


@router.post("/requests/{request_id}/documents/{attachment_id}/release-copy", response_model=RecordsOperationRead)
async def attach_native_release_copy(
    request_id: uuid.UUID, attachment_id: uuid.UUID, data: AttachReleaseCopy, request: Request,
    session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    return await file_operation(session, req, actor, request.state.native_role,
                                "add-records-release-copy", data, request.app.state.desktop_profile_root, attachment_id)


@router.post("/requests/{request_id}/artifacts", response_model=ArtifactPlan)
async def prepare_native_artifact(
    request_id: uuid.UUID, data: PrepareArtifact, request: Request,
    session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    try:
        result = await artifacts.prepare_artifact(session, req, RecordsActor(actor, request.state.native_role), data.kind,
            demo_fixture=await demo_marker(request, session))
        await session.commit()
        return result
    except ValueError as error:
        await session.rollback()
        raise HTTPException(400, str(error)) from None


@router.post("/requests/{request_id}/artifacts/{artifact_id}/complete", response_model=RecordsOperationRead)
async def complete_native_artifact(
    request_id: uuid.UUID, artifact_id: uuid.UUID, data: CompleteArtifact, request: Request,
    session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    try:
        message = await artifacts.complete_artifact(session, req, RecordsActor(actor, request.state.native_role),
                                                    artifact_id, data.export_path, request.app.state.desktop_profile_root)
        result = RecordsOperationRead(action="complete-records-artifact", message=message, request=await request_view(session, req))
        await session.commit()
        return result
    except ValueError as error:
        await session.rollback()
        raise HTTPException(400, str(error)) from None


@router.post("/requests", response_model=NativeRequestRead, status_code=201)
async def create_native_request(
    data: StaffRecordsIntake,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    actor: User = Depends(native_records_user),
):
    req = await service.create_native_records_request(
        session, service.RequestIntake(
            requester_name=data.requester, description=data.summary,
            statutory_deadline=datetime.combine(
                date.fromisoformat(data.deadline), time(), timezone.utc
            ),
        ),
        actor=actor, native_role=request.state.native_role,
        deadline_label=data.deadline, deadline_basis=data.deadlineBasis,
    )
    await session.commit()
    return req


@router.get("/requests/{request_id}", response_model=NativeRequestRead)
async def get_native_request(
    request_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    actor: User = Depends(native_records_user),
):
    # The native capability boundary is installation-wide today; do not
    # silently impose the web department guard or promote a native staff user.
    req = await session.get(RecordsRequest, request_id)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    return req


@router.get("/requests/{request_id}/view", response_model=RecordsView)
async def get_native_request_view(
    request_id: uuid.UUID,
    session: AsyncSession = Depends(get_async_session),
    actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    return await request_view(session, req)


@router.get("/requests/{request_id}/draft-context")
async def native_draft_context(
    request_id: uuid.UUID, session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    try:
        workflow.ensure_active(req)
        view = await request_view(session, req)
        if not view.search_notes and not view.citations:
            raise ValueError("Record at least one search note or citation before generating a local AI records draft.")
        prompt = ("Draft an internal public records response for staff review. Use only the facts below. "
                  "Do not claim legal authority beyond the cited notes. Keep the response concise and leave placeholders for attachments if needed.\n\n"
                  f"Requester: {view.requester}\nDeadline: {view.deadline}\nRequest summary: {view.summary}\n"
                  f"Fee estimate: {view.fee_estimate}\n")
        for label, rows in (("Request messages", view.messages), ("Attached documents", view.documents),
                            ("Clarification notes", view.clarification_notes), ("Search notes", view.search_notes),
                            ("Search sessions", view.search_sessions), ("Exemption review notes", view.exemption_reviews),
                            ("Exemption decisions", view.exemption_decisions), ("Citations/source notes", view.citations)):
            prompt += f"{label}: {artifacts.rows_text(rows)}\n"
        return {"prompt": prompt, "previous_response_sha256": artifacts.text_hash(req.response_draft or "")}
    except ValueError as error:
        raise HTTPException(400, str(error)) from None


@router.post("/requests/{request_id}/generated-draft", response_model=RecordsOperationRead)
async def native_generated_draft(
    request_id: uuid.UUID, data: GeneratedDraft, request: Request,
    session: AsyncSession = Depends(get_async_session), actor: User = Depends(native_records_user),
):
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    try:
        workflow.ensure_active(req)
        if artifacts.text_hash(req.response_draft or "") != data.previous_response_sha256:
            raise HTTPException(409, "The draft changed during generation. Refresh before generating again.")
        workflow.replace_response_text(req, data.text)
        principal = RecordsActor(actor, request.state.native_role)
        await workflow.record_progress(
            session, req, principal, action="suggest-records-response", status="local AI draft ready for review",
            canonical_status=workflow.RequestStatus.DRAFTED, timeline_action="local AI draft generated",
            timeline_actor="local model", timeline_note=f"Draft generated with {data.model}; human approval still required.",
            public_label="Response drafting", public_summary="A response draft is ready for human staff review.",
            audit_note=f"Generated local AI records response draft with {data.model}; human approval still required.",
        )
        result = RecordsOperationRead(action="suggest-records-response", message="Local AI records draft generated. Review, edit, and approve with citations before export.",
                                      request=await request_view(session, req))
        await session.commit()
        return result
    except ValueError as error:
        await session.rollback()
        raise HTTPException(400, str(error)) from None


@router.post("/requests/{request_id}/actions", response_model=RecordsOperationRead)
async def native_request_operation(
    request_id: uuid.UUID,
    command: RecordsCommand,
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    actor: User = Depends(native_records_user),
):
    # One owner/transaction for the request and all its current evidence. The
    # whole-profile desktop cutover is later; this is not per-action routing.
    req = await session.get(RecordsRequest, request_id, with_for_update=True)
    if req is None:
        raise HTTPException(404, "Records request not found.")
    try:
        message = await apply_command(session, req, RecordsActor(actor, request.state.native_role), command)
    except ValueError as error:
        await session.rollback()
        raise HTTPException(400, str(error)) from None
    # Build the typed result before commit: a bad projection must not commit a
    # mutation and then masquerade as a safe-to-repeat validation failure.
    view = await request_view(session, req)
    result = RecordsOperationRead(action=command.action, message=message, request=view)
    await session.commit()
    return result
