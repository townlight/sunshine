"""Resolve native capabilities to an existing SQL actor without role elevation."""
from fastapi import HTTPException
from sqlalchemy import func, select

from app.auth.desktop_session import validate_native_session
from app.models.user import User, UserRole


async def mapped_native_actor(request, session, proof, module_id: str) -> User:
    try:
        principal = validate_native_session(proof, profile_root=request.app.state.desktop_profile_root)
    except PermissionError as error:
        raise HTTPException(401, str(error)) from None
    if (module_id not in request.app.state.desktop_enabled_modules
            or not principal.allows_module(module_id)):
        raise HTTPException(403, "This account/profile cannot use this capability.")
    if not request.app.state.desktop_domain_enabled:
        raise HTTPException(503, "Domain migration is not activated; no work was accepted.")
    user = (await session.execute(select(User).where(func.lower(User.email) == principal.email))).scalar_one_or_none()
    expected_role = UserRole.ADMIN if principal.role == "local-admin" else UserRole.STAFF
    if (user is None or not user.is_active or user.must_change_password or user.role != expected_role):
        raise HTTPException(403, "The native account has no valid mapped identity.")
    request.state.native_actor_id = user.id
    request.state.native_role = principal.role
    return user
