"""Contract tests for Records AI accepting TownlightCore suite staff sessions."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient

from townlight_records.auth.suite_session import issue_suite_session_for_test, revoke_suite_session_for_test
from tests.conftest import _create_test_user
from townlight_records.models.user import UserRole


@pytest.mark.asyncio
async def test_records_ai_accepts_suite_session_after_password_rotation(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOWNLIGHT_CORE_SUITE_SESSION_SECRET", "records-suite-session-secret")
    email = f"suite-{uuid.uuid4().hex[:8]}@example.gov"
    await _create_test_user(email, "rotatedpass123", "Suite Admin", UserRole.ADMIN)
    token = issue_suite_session_for_test(
        subject=email,
        roles={"records_admin", "clerk_admin", "code_admin"},
        session_id="records-suite-session",
    )

    response = await client.get(
        "/admin/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["suite_session"]["subject"] == email


@pytest.mark.asyncio
async def test_records_ai_rejects_revoked_suite_session(
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TOWNLIGHT_CORE_SUITE_SESSION_SECRET", "records-suite-session-secret")
    token = issue_suite_session_for_test(
        subject="revoked@example.gov",
        roles={"records_admin"},
        session_id="records-revoked-session",
    )
    revoke_suite_session_for_test("records-revoked-session")

    response = await client.get(
        "/admin/status",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 401
    assert response.json()["detail"]["message"] == "Suite session has been revoked."
