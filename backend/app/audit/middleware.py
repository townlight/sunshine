import hashlib
import uuid

import jwt
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from app.audit.logger import write_audit_log
from app.config import settings
from app.database import async_session_maker

SKIP_PATHS = {"/health", "/docs", "/openapi.json", "/redoc"}

# GET paths that should still be audit-logged (security-relevant)
AUDIT_GET_PREFIXES = ("/audit/", "/admin/")


def _should_skip(method: str, path: str, status_code: int) -> bool:
    """Determine whether this request should be skipped from audit logging."""
    # Always skip explicitly excluded paths
    if path in SKIP_PATHS or path.startswith("/static"):
        return True

    # Skip 404 responses
    if status_code == 404:
        return True

    # For GET requests, only log security-relevant paths
    if method == "GET":
        return not any(path.startswith(prefix) for prefix in AUDIT_GET_PREFIXES)

    # Log all other methods (POST, PUT, PATCH, DELETE) regardless of status
    return False


def _extract_user_id(request: Request) -> uuid.UUID | None:
    """Extract user_id from JWT Bearer token in Authorization header."""
    native_actor = getattr(request.state, "native_actor_id", None)
    if isinstance(native_actor, uuid.UUID):
        return native_actor
    auth_header = request.headers.get("authorization", "")
    if not auth_header.startswith("Bearer "):
        return None

    token = auth_header[7:]  # Strip "Bearer "
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=["HS256"])
        sub = payload.get("sub")
        if sub:
            return uuid.UUID(sub)
    except Exception:
        pass
    return None


class AuditMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        # Quick skip for obvious non-audit paths before processing
        if request.url.path in SKIP_PATHS or request.url.path.startswith("/static"):
            return await call_next(request)

        response = await call_next(request)

        if _should_skip(request.method, request.url.path, response.status_code):
            return response

        user_id = _extract_user_id(request)
        path = request.url.path
        action = f"{request.method} {path}"
        # Route instances with multiple UUIDs can exceed action's String(100).
        # Keep complete request evidence in the hashed details, without changing
        # historical rows or silently losing the ancillary HTTP audit entry.
        if len(action) > 100:
            action = f"{request.method} http_request"
        resource_id = path if len(path) <= 255 else "sha256:" + hashlib.sha256(path.encode()).hexdigest()

        try:
            async with async_session_maker() as session:
                await write_audit_log(
                    session=session,
                    action=action,
                    resource_type="http_request",
                    resource_id=resource_id,
                    user_id=user_id,
                    details={
                        "method": request.method,
                        "path": request.url.path,
                        "query": str(request.url.query) if request.url.query else None,
                        "status_code": response.status_code,
                        "client_ip": request.client.host if request.client else None,
                    },
                )
        except Exception:
            pass

        return response
