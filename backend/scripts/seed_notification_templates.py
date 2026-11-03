"""Seed the 7 canonical notification event templates (Spec Section 8.4)."""
import asyncio

from sqlalchemy import select

from townlight_records.database import async_session_maker
from townlight_records.models.notifications import NotificationTemplate
from townlight_records.models.user import User


NOTIFICATION_TEMPLATES = [
    {
        "event_type": "request_received",
        "channel": "email",
        "subject_template": "Records Request Received — {request_id}",
        "body_template": "Dear {requester_name},\n\nYour public records request has been received and assigned reference number {request_id}.\n\nWe will process your request in accordance with applicable public records law. You will receive updates as your request progresses.\n\nThank you,\n{city_name} Records Office",
    },
    {
        "event_type": "request_clarification_needed",
        "channel": "email",
        "subject_template": "Clarification Needed — Records Request {request_id}",
        "body_template": "Dear {requester_name},\n\nWe need additional information to process your records request {request_id}. Please contact our office at your earliest convenience to clarify your request.\n\nThank you,\n{city_name} Records Office",
    },
    {
        "event_type": "request_assigned",
        "channel": "in_app",
        "subject_template": "Request Assigned — {request_id}",
        "body_template": "Records request {request_id} from {requester_name} has been assigned to you for processing.",
    },
    {
        "event_type": "request_deadline_approaching",
        "channel": "email",
        "subject_template": "Deadline Approaching — Records Request {request_id}",
        "body_template": "Records request {request_id} has a statutory deadline approaching within 3 days. Please ensure all responsive documents have been reviewed and a response is prepared.",
    },
    {
        "event_type": "request_deadline_overdue",
        "channel": "email",
        "subject_template": "OVERDUE — Records Request {request_id}",
        "body_template": "Records request {request_id} is past its statutory deadline. Immediate action is required. Please contact your supervisor if you need assistance completing this request.",
    },
    {
        "event_type": "request_fulfilled",
        "channel": "email",
        "subject_template": "Records Ready — Request {request_id}",
        "body_template": "Dear {requester_name},\n\nThe records responsive to your request {request_id} are ready. Please contact our office to arrange delivery or pickup.\n\nThank you,\n{city_name} Records Office",
    },
    {
        "event_type": "request_closed",
        "channel": "email",
        "subject_template": "Request Closed — {request_id}",
        "body_template": "Dear {requester_name},\n\nYour records request {request_id} has been closed. If you have questions about this request or need additional records, please submit a new request.\n\nThank you,\n{city_name} Records Office",
    },
    # --- Templates for status transitions dispatched by the router ---
    {
        "event_type": "request_searching",
        "channel": "email",
        "subject_template": "Search In Progress — Records Request {request_id}",
        "body_template": "Dear {requester_name},\n\nWe are actively searching for records responsive to your request {request_id}. You will be notified when the search is complete.\n\nThank you,\n{city_name} Records Office",
    },
    {
        "event_type": "request_in_review",
        "channel": "email",
        "subject_template": "Under Review — Records Request {request_id}",
        "body_template": "Dear {requester_name},\n\nYour records request {request_id} is now under review. Our team is examining the responsive documents for any applicable exemptions before release.\n\nThank you,\n{city_name} Records Office",
    },
    {
        "event_type": "request_ready_for_release",
        "channel": "in_app",
        "subject_template": "Ready for Release — {request_id}",
        "body_template": "Records request {request_id} has been marked ready for release and is awaiting final approval.",
    },
    {
        "event_type": "request_approved",
        "channel": "email",
        "subject_template": "Request Approved — Records Request {request_id}",
        "body_template": "Dear {requester_name},\n\nYour records request {request_id} has been approved for release. You will receive the responsive documents shortly.\n\nThank you,\n{city_name} Records Office",
    },
    {
        "event_type": "request_drafted",
        "channel": "in_app",
        "subject_template": "Response Drafted — {request_id}",
        "body_template": "A draft response has been prepared for records request {request_id}. Please review and revise before submitting for approval.",
    },
]


async def seed():
    async with async_session_maker() as session:
        # Require an admin user for created_by attribution
        result = await session.execute(select(User).limit(1))
        user = result.scalar_one_or_none()
        if not user:
            print("No users in database. Run the application first.")
            return

        created = 0
        skipped = 0

        for tmpl_data in NOTIFICATION_TEMPLATES:
            existing = await session.execute(
                select(NotificationTemplate).where(
                    NotificationTemplate.event_type == tmpl_data["event_type"],
                )
            )
            if existing.scalar_one_or_none():
                print(f"  Skipped (exists): {tmpl_data['event_type']}")
                skipped += 1
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
            print(f"  Created: {tmpl_data['event_type']}")
            created += 1

        await session.commit()
        print(f"\nNotification templates seeded: {created} created, {skipped} skipped")


if __name__ == "__main__":
    asyncio.run(seed())
