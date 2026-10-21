import uuid

from fastapi import Depends, HTTPException, Request, status
from fastapi_users import FastAPIUsers
from jwt import InvalidTokenError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.backend import auth_backend
from app.auth.manager import get_user_manager
from app.auth.suite_session import (
    SuiteSessionUser,
    validate_suite_session,
    validate_suite_session_for_user,
)
from app.database import get_async_session
from app.models.user import User, UserRole

fastapi_users = FastAPIUsers[User, uuid.UUID](get_user_manager, [auth_backend])

_optional_current_active_user = fastapi_users.current_user(active=True, optional=True)


async def current_active_user(
    request: Request,
    user: User | None = Depends(_optional_current_active_user),
    session: AsyncSession = Depends(get_async_session),
) -> User:
    if user is None:
        user = await _suite_session_user_from_request(request, session)

    if user.must_change_password and not request.url.path.startswith("/users/me"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "message": "Password rotation required before continuing.",
                "fix": (
                    "Open your account settings and change the initial "
                    "administrator password before using staff features."
                ),
            },
        )
    return user


async def _suite_session_user_from_request(request: Request, session: AsyncSession) -> User:
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    token = auth_header.removeprefix("Bearer ").strip()
    try:
        suite_session = validate_suite_session(token)
    except PermissionError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "message": str(exc),
                "fix": "Return to the Townlight launcher and sign in again.",
            },
        ) from exc
    except (InvalidTokenError, ValueError):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    result = await session.execute(select(User).where(User.email == suite_session.subject))
    user = result.scalar_one_or_none()
    if user is None or not user.is_active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")

    try:
        validate_suite_session_for_user(
            token,
            user=SuiteSessionUser(
                email=user.email,
                roles=suite_session.roles,
                must_change_password=user.must_change_password
                and not request.url.path.startswith("/users/me"),
            ),
        )
    except PermissionError as exc:
        status_code = (
            status.HTTP_403_FORBIDDEN
            if "Password rotation required" in str(exc)
            else status.HTTP_401_UNAUTHORIZED
        )
        raise HTTPException(
            status_code=status_code,
            detail={
                "message": str(exc),
                "fix": (
                    "Open your account settings and change the initial "
                    "administrator password before using staff features."
                    if status_code == status.HTTP_403_FORBIDDEN
                    else "Return to the Townlight launcher and sign in again."
                ),
            },
        ) from exc

    request.state.suite_session = suite_session.as_response()
    return user

# Role hierarchy: admin > reviewer > staff > liaison > read_only > public
ROLE_HIERARCHY = {
    UserRole.ADMIN: 6,
    UserRole.REVIEWER: 5,
    UserRole.STAFF: 4,
    UserRole.LIAISON: 3,
    UserRole.READ_ONLY: 2,
    UserRole.PUBLIC: 1,
}


def require_role(minimum_role: UserRole):
    """Dependency that enforces a minimum role level."""

    async def _check_role(user: User = Depends(current_active_user)) -> User:
        if ROLE_HIERARCHY.get(user.role, 0) < ROLE_HIERARCHY[minimum_role]:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Requires {minimum_role.value} role or higher",
            )
        return user

    return _check_role


def require_department_scope(user: User, resource_department_id: uuid.UUID | None) -> None:
    """Fail-closed department access check. Raises HTTP 403 on deny.

    Rules:
    - Admin: always allowed.
    - Non-admin with ``user.department_id is None``: denied.
    - Non-admin with ``resource_department_id is None``: denied (no shared-resource shortcut).
    - Non-admin otherwise: allowed iff ``user.department_id == resource_department_id``.

    Call this after loading the resource. For list endpoints, apply the
    equivalent ``WHERE`` clause on the query instead::

        if user.role != UserRole.ADMIN:
            if user.department_id is None:
                raise HTTPException(403, ...)
            stmt = stmt.where(Model.department_id == user.department_id)
    """
    if user.role == UserRole.ADMIN:
        return
    if user.department_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: user is not assigned to a department",
        )
    if resource_department_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource has no department scope",
        )
    if user.department_id != resource_department_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: resource belongs to another department",
        )


def has_department_access(user: User, resource_department_id: uuid.UUID | None) -> bool:
    """Non-raising variant of ``require_department_scope``.

    Returns ``True`` if the user would pass the same fail-closed rules,
    ``False`` otherwise. Use this when the caller needs to unify the response
    for "resource does not exist" and "resource exists but you cannot access
    it" — for example, to prevent an information-disclosure side channel on
    routes where the resource ID is the only path parameter.

    Rules match ``require_department_scope`` exactly:
    - Admin: True.
    - Non-admin with ``user.department_id is None``: False.
    - Non-admin with ``resource_department_id is None``: False.
    - Non-admin otherwise: ``user.department_id == resource_department_id``.
    """
    if user.role == UserRole.ADMIN:
        return True
    if user.department_id is None:
        return False
    if resource_department_id is None:
        return False
    return user.department_id == resource_department_id


def require_department_filter(user: User) -> uuid.UUID | None:
    """Resolve the department_id to apply as a WHERE-clause filter on list
    or aggregate endpoints. Fails closed for non-admin users with no
    department.

    Returns:
        ``None`` for admin users — no filter; they see every department.
        ``user.department_id`` for non-admin users with a department assignment.

    Raises:
        HTTP 403 for non-admin users with ``user.department_id is None``.
        This is the list/aggregate analog of
        :func:`require_department_or_404` — for list endpoints there is no
        specific resource ID to probe, so a semantic 403 is correct; the
        404-unification rationale does not apply.

    Use this in list/aggregate/search handlers to avoid the "if user.role
    != UserRole.ADMIN and user.department_id is not None" fail-open pattern
    that silently skips the dept filter for a null-dept non-admin.
    """
    if user.role == UserRole.ADMIN:
        return None
    if user.department_id is None:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: user is not assigned to a department",
        )
    return user.department_id


def require_department_or_404(
    user: User,
    resource_department_id: uuid.UUID | None,
    detail: str = "Not found",
) -> None:
    """Dept-scope check with 404-unification.

    Raises HTTP 404 (not 403) on denial so the external response is identical
    to "resource does not exist". This prevents status-code-based disclosure
    of cross-department resource existence: an attacker who guesses or
    acquires a valid resource UUID cannot distinguish "exists in another
    dept" (would have been 403) from "does not exist" (404) — both return
    the same 404 with the same detail string.

    Use this on routes where the path parameter alone is enough to identify
    a scoped resource (every ``@router.*("/{some_id}..")`` handler that
    loads that resource and relies on a related record's department_id).
    Use :func:`require_department_scope` when a semantic 403 is correct —
    e.g., admin surfaces where the caller should know it's an authz issue,
    or flows where the path structure already requires the caller to know
    the parent-scope identity.
    """
    if not has_department_access(user, resource_department_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=detail)
