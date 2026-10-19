import logging
import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.notifications import NotificationLog, NotificationTemplate

logger = logging.getLogger(__name__)


async def queue_notification(
    session: AsyncSession,
    event_type: str,
    recipient_email: str,
    request_id: uuid.UUID | None = None,
    context_data: dict | None = None,
) -> NotificationLog | None:
    """Look up a notification template, render it, and create a log entry.

    Returns the NotificationLog entry if a matching active template was found,
    or None if no template exists for the event_type.

    The rendered notification is logged with status 'queued'. Actual delivery
    (SMTP, etc.) will be handled by a Celery task once configured.
    """
    result = await session.execute(
        select(NotificationTemplate).where(
            NotificationTemplate.event_type == event_type,
            NotificationTemplate.is_active.is_(True),
        )
    )
    template = result.scalar_one_or_none()
    if not template:
        logger.warning("No active template for event_type=%s", event_type)
        return None

    ctx = context_data or {}

    try:
        rendered_subject = template.subject_template.format(**ctx)
        rendered_body = template.body_template.format(**ctx)
    except KeyError as e:
        logger.error(
            "Template render failed for event_type=%s: missing key %s",
            event_type,
            e,
        )
        log_entry = NotificationLog(
            template_id=template.id,
            recipient_email=recipient_email,
            request_id=request_id,
            channel=template.channel,
            status="failed",
            error_message=f"Template render error: missing key {e}",
        )
        session.add(log_entry)
        await session.flush()
        return log_entry

    log_entry = NotificationLog(
        template_id=template.id,
        recipient_email=recipient_email,
        request_id=request_id,
        channel=template.channel,
        subject=rendered_subject,
        body=rendered_body,
        status="queued",
    )
    session.add(log_entry)
    await session.flush()

    logger.info(
        "Notification queued: id=%s event=%s recipient=%s subject=%s",
        log_entry.id,
        event_type,
        recipient_email,
        rendered_subject,
    )

    return log_entry


async def queue_local_notification(
    session: AsyncSession, *, request_id: uuid.UUID | None, module_id: str,
    audience: str, subject: str, body: str, created_at: datetime,
) -> NotificationLog:
    """Existing native manual outbox; not SMTP and not automatically queued."""
    entry = NotificationLog(
        request_id=request_id, module_id=module_id, audience=audience,
        recipient_email="", channel="local notification outbox",
        subject=subject, body=body, status="ready to send", created_at=created_at,
    )
    session.add(entry)
    await session.flush()
    return entry
