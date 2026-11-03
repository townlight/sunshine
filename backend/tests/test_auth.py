import uuid

import pytest
from sqlalchemy import select
from httpx import AsyncClient

from tests.conftest import _create_test_user, test_session_maker
from townlight_records.models.user import User, UserRole


@pytest.mark.asyncio
async def test_admin_can_create_user(client: AsyncClient, admin_token: str):
    """Admin can create a user via the admin endpoint (public registration removed)."""
    resp = await client.post(
        "/admin/users",
        json={
            "email": f"test-{uuid.uuid4().hex[:8]}@example.com",
            "password": "securepassword123",
            "full_name": "Jane Clerk",
            "role": "staff",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    data = resp.json()
    assert data["full_name"] == "Jane Clerk"
    assert data["role"] == "staff"
    assert data["is_active"] is True


@pytest.mark.asyncio
async def test_login_returns_jwt(client: AsyncClient):
    email = f"login-{uuid.uuid4().hex[:8]}@example.com"
    await _create_test_user(email, "testpass123", "Test User", UserRole.STAFF)
    resp = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": "testpass123"},
    )
    assert resp.status_code == 200
    assert "access_token" in resp.json()


@pytest.mark.asyncio
async def test_me_endpoint(client: AsyncClient):
    email = f"me-{uuid.uuid4().hex[:8]}@example.com"
    await _create_test_user(email, "testpass123", "Me User", UserRole.REVIEWER)
    login = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": "testpass123"},
    )
    token = login.json()["access_token"]
    resp = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["email"] == email
    assert resp.json()["role"] == "reviewer"


@pytest.mark.asyncio
async def test_unauthenticated_rejected(client: AsyncClient):
    resp = await client.get("/users/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_role_enforcement_rejects_insufficient_role(client: AsyncClient, staff_token: str):
    """Staff user should get 403 on admin-only endpoints."""
    resp = await client.get(
        "/admin/status",
        headers={"Authorization": f"Bearer {staff_token}"},
    )
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_public_registration_disabled(client: AsyncClient):
    """Public registration endpoint should not exist."""
    resp = await client.post(
        "/auth/register",
        json={
            "email": "shouldfail@example.com",
            "password": "testpass123",
            "full_name": "Nobody",
        },
    )
    assert resp.status_code in (404, 405)


@pytest.mark.asyncio
async def test_initial_admin_must_rotate_password_before_staff_routes(client: AsyncClient):
    email = f"rotate-{uuid.uuid4().hex[:8]}@example.com"
    old_password = "initialpass123"
    new_password = "rotatedpass123"
    await _create_test_user(email, old_password, "Initial Admin", UserRole.ADMIN)

    async with test_session_maker() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.must_change_password = True
        await session.commit()

    login = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": old_password},
    )
    assert login.status_code == 200
    token = login.json()["access_token"]

    blocked = await client.get(
        "/admin/status",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert blocked.status_code == 403
    assert blocked.json()["detail"]["message"] == "Password rotation required before continuing."

    me = await client.get("/users/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200
    assert me.json()["must_change_password"] is True

    rotated = await client.patch(
        "/users/me",
        headers={"Authorization": f"Bearer {token}"},
        json={"password": new_password},
    )
    assert rotated.status_code == 200

    relogin = await client.post(
        "/auth/jwt/login",
        data={"username": email, "password": new_password},
    )
    assert relogin.status_code == 200
    rotated_token = relogin.json()["access_token"]

    allowed = await client.get(
        "/admin/status",
        headers={"Authorization": f"Bearer {rotated_token}"},
    )
    assert allowed.status_code == 200

    after = await client.get("/users/me", headers={"Authorization": f"Bearer {rotated_token}"})
    assert after.status_code == 200
    assert after.json()["must_change_password"] is False
