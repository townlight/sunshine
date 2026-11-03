"""Integration tests: every router-dispatched event_type must produce a NotificationLog row.

Finding 1 from 2026-04-13 audit: the router dispatches event_types that had no
matching seed template, causing queue_notification() to silently no-op.  These
tests ensure every dispatch path creates an actual notification record.
"""

import pytest

from townlight_records.notifications.service import queue_notification
from townlight_records.models.notifications import NotificationLog, NotificationTemplate


# Every event_type that the requests router dispatches.
# Source: backend/app/requests/router.py (grep for queue_notification).
ROUTER_DISPATCHED_EVENT_TYPES = [
    # From create_request (POST /) — hardcoded
    "request_received",
    # From update_request (PATCH) — f"request_{data.status.value}"
    "request_searching",
    "request_in_review",
    "request_clarification_needed",
    "request_assigned",
    "request_fulfilled",
    "request_closed",
    "request_drafted",
    "request_ready_for_release",
    "request_approved",
    # From dedicated endpoints (hardcoded strings)
    "request_in_review",        # submit_for_review
    "request_ready_for_release",  # mark_ready_for_release
    "request_approved",          # approve_request
    "request_drafted",           # reject_request
]

# Deduplicated set of event_types that MUST have a seed template.
REQUIRED_EVENT_TYPES = sorted(set(ROUTER_DISPATCHED_EVENT_TYPES))


@pytest.mark.asyncio
async def test_seed_templates_cover_all_dispatched_event_types(client):
    """The seed script must define a template for every router-dispatched event_type."""
    from scripts.seed_notification_templates import NOTIFICATION_TEMPLATES

    seeded_event_types = {t["event_type"] for t in NOTIFICATION_TEMPLATES}

    missing = set(REQUIRED_EVENT_TYPES) - seeded_event_types
    assert missing == set(), (
        f"Seed script is missing templates for router-dispatched event_types: {missing}"
    )


@pytest.mark.asyncio
async def test_queue_notification_creates_log_for_each_event_type(client, admin_token: str):
    """queue_notification() must create a NotificationLog row for every dispatched event_type."""
    from tests.conftest import test_session_maker
    from scripts.seed_notification_templates import NOTIFICATION_TEMPLATES
    from townlight_records.models.user import User
    from sqlalchemy import select

    # admin_token fixture creates a user; fetch it for template attribution
    async with test_session_maker() as session:
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        assert user is not None, "Test DB must have at least one user (created by admin_token fixture)"

        for tmpl_data in NOTIFICATION_TEMPLATES:
            existing = await session.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.event_type == tmpl_data["event_type"],
                )
            )
            if existing.scalar_one_or_none():
                continue
            template = NotificationTemplate(
                event_type=tmpl_data["event_type"],
                channel=tmpl_data["channel"],
                subject_template=tmpl_data["subject_template"],
                body_template=tmpl_data["body_template"],
                is_active=True,
                created_by=user.id,
            )
            session.add(template)
        await session.commit()

    # Now dispatch each router event_type and assert a log row is created
    failed_types = []
    async with test_session_maker() as session:
        for event_type in REQUIRED_EVENT_TYPES:
            log = await queue_notification(
                session=session,
                event_type=event_type,
                recipient_email="test@city.gov",
                context_data={
                    "request_id": "REQ-001",
                    "requester_name": "Test User",
                    "city_name": "Test City",
                },
            )
            if log is None:
                failed_types.append(event_type)
            else:
                assert isinstance(log, NotificationLog)
                assert log.status == "queued"
        await session.commit()

    assert failed_types == [], (
        f"queue_notification() returned None (no template match) for: {failed_types}"
    )


# The exact keys the router passes to queue_notification context_data.
# If a template uses a variable not in this set, it will KeyError at render time.
# This must be kept in sync with requests/router.py.
ROUTER_CONTEXT_KEYS = {
    "requester_name": "Test User",
    "request_id": "REQ-001",
    "status": "searching",
    "city_name": "Test City",
}


@pytest.mark.asyncio
async def test_all_templates_render_with_router_context_keys(client, admin_token: str):
    """Every template must render cleanly with ONLY the keys the router actually passes.

    Catches the {city_name} KeyError bug: templates referenced variables that no
    call site provided, causing silent render failures in production.
    """
    from scripts.seed_notification_templates import NOTIFICATION_TEMPLATES

    render_failures = []
    for tmpl in NOTIFICATION_TEMPLATES:
        try:
            tmpl["subject_template"].format(**ROUTER_CONTEXT_KEYS)
            tmpl["body_template"].format(**ROUTER_CONTEXT_KEYS)
        except KeyError as e:
            render_failures.append(
                f"{tmpl['event_type']}: missing key {e} in router context_data"
            )

    assert render_failures == [], (
        "Templates reference variables not provided by the router:\n"
        + "\n".join(render_failures)
    )


@pytest.mark.asyncio
async def test_create_request_dispatches_request_received(client, admin_token: str):
    """POST /requests/ must dispatch request_received when requester_email is present.

    Regression guard: create_request was missing a queue_notification call until
    2026-04-14. The other notification_dispatch tests verify templates exist and
    queue_notification works in isolation, but neither exercises create_request
    end-to-end. This test asserts the wiring itself.
    """
    from tests.conftest import test_session_maker
    from scripts.seed_notification_templates import NOTIFICATION_TEMPLATES
    from townlight_records.models.user import User
    from sqlalchemy import select

    # Ensure the request_received template exists in the test DB
    async with test_session_maker() as session:
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        assert user is not None

        existing = await session.execute(
            select(NotificationTemplate).where(
                NotificationTemplate.event_type == "request_received",
            )
        )
        if not existing.scalar_one_or_none():
            tmpl_data = next(
                (t for t in NOTIFICATION_TEMPLATES if t["event_type"] == "request_received"),
                None,
            )
            assert tmpl_data is not None, (
                "Seed NOTIFICATION_TEMPLATES is missing 'request_received' — "
                "must be added before this test can run."
            )
            session.add(NotificationTemplate(
                event_type=tmpl_data["event_type"],
                channel=tmpl_data["channel"],
                subject_template=tmpl_data["subject_template"],
                body_template=tmpl_data["body_template"],
                is_active=True,
                created_by=user.id,
            ))
            await session.commit()

    # POST a new request with a requester_email
    unique_email = "request-received-test@example.test"
    resp = await client.post(
        "/requests/",
        json={
            "requester_name": "Request Received Test",
            "requester_email": unique_email,
            "description": "Verify create_request fires request_received notification",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    req_id = resp.json()["id"]

    # Assert a notification_log row was written for this request, joined to the
    # request_received template
    async with test_session_maker() as session:
        result = await session.execute(
            select(NotificationLog)
            .join(NotificationTemplate, NotificationLog.template_id == NotificationTemplate.id)
            .where(
                NotificationLog.recipient_email == unique_email,
                NotificationTemplate.event_type == "request_received",
            )
        )
        log_row = result.scalar_one_or_none()

    assert log_row is not None, (
        f"Expected a notification_log row with event_type='request_received' for "
        f"recipient={unique_email} after POST /requests/. None was found, which "
        f"means create_request is not calling queue_notification('request_received')."
    )
    assert log_row.status == "queued"
    assert str(log_row.request_id) == req_id


@pytest.mark.asyncio
async def test_create_request_skips_dispatch_when_no_email(client, admin_token: str):
    """POST /requests/ without a requester_email must not raise and must not create a log row."""
    from tests.conftest import test_session_maker
    from sqlalchemy import select

    resp = await client.post(
        "/requests/",
        json={
            "requester_name": "No Email Test",
            "description": "Verify create_request handles missing email gracefully",
        },
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 201
    req_id = resp.json()["id"]

    # No notification_log row should exist for this request
    async with test_session_maker() as session:
        result = await session.execute(
            select(NotificationLog).where(NotificationLog.request_id == req_id)
        )
        rows = result.scalars().all()

    assert rows == [], (
        f"Expected no notification_log rows for a request with no requester_email, "
        f"found {len(rows)}."
    )


@pytest.mark.asyncio
async def test_audit_export_csv_endpoint(client, admin_token: str):
    """GET /audit/export?format=csv returns CSV with correct headers."""
    resp = await client.get(
        "/audit/export?format=csv",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    assert resp.status_code == 200
    assert "text/csv" in resp.headers.get("content-type", "")
    lines = resp.text.strip().split("\n")
    assert len(lines) >= 1  # At least the header row
    header = lines[0]
    assert "timestamp" in header
    assert "action" in header


@pytest.mark.asyncio
async def test_audit_export_requires_auth(client):
    """GET /audit/export without token returns 401."""
    resp = await client.get("/audit/export?format=csv")
    assert resp.status_code == 401
