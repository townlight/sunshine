"""Native authentication/translation only; Records owns the domain operation."""

from datetime import date, datetime, time, timezone
from pathlib import Path
import uuid

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.desktop_session import validate_native_session
from app.database import get_async_session
from app.desktop_bridge.schemas import NativeRequestRead, RecordsCommand, RecordsOperationRead, RecordsView, StaffRecordsIntake
from app.desktop_bridge.projection import request_view
from app.desktop_bridge.records import apply_command
from app.models.request import RecordsRequest
from app.models.user import User, UserRole
from app.requests import service
from app.requests.workflow import RecordsActor

router = APIRouter(prefix="/desktop/v1", tags=["native-desktop"])


async def native_records_user(
    request: Request,
    session: AsyncSession = Depends(get_async_session),
    proof: str | None = Header(default=None, alias="X-Townlight-Session"),
) -> User:
    root: Path = request.app.state.desktop_profile_root
    try:
        principal = validate_native_session(proof, profile_root=root)
    except PermissionError as error:
        raise HTTPException(401, str(error)) from None
    if ("civicrecords-ai" not in request.app.state.desktop_enabled_modules
            or not principal.allows_module("civicrecords-ai")):
        raise HTTPException(403, "This account/profile cannot use Records.")
    if not request.app.state.desktop_domain_enabled:
        raise HTTPException(503, "Records migration is not activated; no work was accepted.")
    user = (await session.execute(
        select(User).where(func.lower(User.email) == principal.email)
    )).scalar_one_or_none()
    expected_role = UserRole.ADMIN if principal.role == "local-admin" else UserRole.STAFF
    if (user is None or not user.is_active or user.must_change_password
            or user.role != expected_role):
        raise HTTPException(403, "The native account has no valid mapped Records identity.")
    request.state.native_actor_id = user.id
    request.state.native_role = principal.role
    return user


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
