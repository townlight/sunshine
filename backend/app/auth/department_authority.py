# SPDX-License-Identifier: AGPL-3.0-only
"""Trusted server-side adapter: verified Records identity -> Core department authority.

This module is the *only* place where a Records request handler turns an already
verified :class:`app.models.user.User` into a CivicCore department authority. It
never reads a department from the request body, query string, header, cookie or
token claim: the department a caller may read comes solely from the persisted
CivicCore grant ledger (``civiccore_department_grant_events``), keyed by
``(scope_id, subject, department_id)``.

Deny by default:

* the deployment scope is configured server-side (``settings.authority_scope_id``);
  an unset or malformed scope refuses the request instead of falling back;
* a subject with no active Core grant receives 403;
* a record whose owning department is not granted is reported as not found, so a
  caller cannot distinguish "exists in another department" from "does not exist";
* there is no admin bypass: Core authority is consulted for every role.

Credential verification stays in :mod:`app.auth.dependencies`; this module only
consumes its result.
"""

from __future__ import annotations

import uuid

from fastapi import HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.user import User
from civiccore.auth import AuthenticatedPrincipal
from civiccore.auth.department_scope import (
    DepartmentAuthority,
    DepartmentAuthorityError,
    active_department_grants,
    resolve_department_authority,
)

ACCESS_DENIED_DETAIL = "Access denied: no department authority for this deployment scope"


def records_department_scope_id() -> str:
    """Return the server-configured deployment scope, or fail closed.

    The scope is a deployment/tenant identifier configured by the operator; it is
    never taken from a request. Records does not hardcode a city.
    """

    scope = (getattr(settings, "authority_scope_id", "") or "").strip()
    if not scope:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: department authority scope is not configured for this deployment",
        )
    return scope


def principal_from_verified_user(request: Request, user: User) -> AuthenticatedPrincipal:
    """Map a verified Records user to a Core principal using server-side facts only.

    ``subject`` is the user's stored account address, ``roles`` is the stored role.
    ``auth_method`` records how this request was actually authenticated: the suite
    session dependency sets ``request.state.suite_session`` when it verified a
    launcher session, otherwise fastapi-users' bearer verification produced the
    user. Both are Core-trusted identity sources; the adapter adds no other path.
    """

    if getattr(request.state, "suite_session", None) is not None:
        auth_method = "suite_session"
    else:
        auth_method = "bearer"
    return AuthenticatedPrincipal(
        token_fingerprint=None,
        roles=frozenset({user.role.value}),
        auth_method=auth_method,
        subject=user.email,
        provider=None,
    )


async def resolve_verified_user_authority(
    session: AsyncSession,
    request: Request,
    user: User,
) -> DepartmentAuthority:
    """Resolve the caller's Core authority from the persisted ledger.

    Raises HTTP 403 when the deployment scope is missing or Core refuses the
    principal (no active grant, untrusted identity source, inactive principal).
    """

    scope_id = records_department_scope_id()
    principal = principal_from_verified_user(request, user)
    grants = await active_department_grants(
        session, scope_id=scope_id, subject=principal.subject or ""
    )
    try:
        return resolve_department_authority(
            principal=principal, scope_id=scope_id, grants=grants
        )
    except DepartmentAuthorityError as exc:
        reason = getattr(exc, "reason", exc.__class__.__name__)
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{ACCESS_DENIED_DETAIL} ({reason})",
        ) from exc


async def enforce_request_department_authority(
    session: AsyncSession,
    request: Request,
    user: User,
    resource_department_id: uuid.UUID | None,
    *,
    not_found_detail: str = "Request not found",
) -> DepartmentAuthority:
    """Require a persisted Core grant for the record's owning department.

    Called only after the record has been loaded and the Records-side identity
    scope check has run. Uses 404 for a record whose department is unknown or not
    granted, matching the existing Records no-leak contract.
    """

    authority = await resolve_verified_user_authority(session, request, user)
    if not authority.entitlements:
        # The subject holds no active department grant at all: that is an
        # authorization refusal, not a statement about any particular record.
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"{ACCESS_DENIED_DETAIL} (no-active-grant)",
        )
    if resource_department_id is None or not authority.permits(resource_department_id):
        # Entitled elsewhere but not here: use the same 404 as "does not exist"
        # so cross-department existence is not disclosed.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail=not_found_detail
        )
    return authority
