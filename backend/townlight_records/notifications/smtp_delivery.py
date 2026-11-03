"""SMTP email delivery for queued notifications.

Processes NotificationLog entries with status 'queued' and sends them
via SMTP. Can be called as a Celery task or directly for testing.
"""

import logging
import smtplib
from datetime import datetime, timezone
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from townlight_records.config import settings
from townlight_records.models.notifications import NotificationLog

logger = logging.getLogger(__name__)


def send_email(
    to_email: str,
    subject: str,
    body: str,
    from_email: str | None = None,
) -> None:
    """Send a single email via SMTP.

    Raises smtplib.SMTPException on failure.
    """
    if not settings.smtp_host:
        raise RuntimeError("SMTP_HOST not configured — cannot send email")

    from_addr = from_email or settings.smtp_from_email

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = from_addr
    msg["To"] = to_email

    # Plain text body
    msg.attach(MIMEText(body, "plain"))

    if settings.smtp_use_tls:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)
        server.starttls()
    else:
        server = smtplib.SMTP(settings.smtp_host, settings.smtp_port)

    try:
        if settings.smtp_username:
            server.login(settings.smtp_username, settings.smtp_password)
        server.sendmail(from_addr, [to_email], msg.as_string())
    finally:
        server.quit()


async def deliver_queued_notifications(session: AsyncSession) -> dict:
    """Process all queued notifications and send via SMTP.

    Returns a summary dict with sent/failed/skipped counts.
    """
    if not settings.smtp_host:
        logger.warning("SMTP_HOST not configured — skipping email delivery")
        return {"sent": 0, "failed": 0, "skipped": 0, "reason": "smtp_not_configured"}

    result = await session.execute(
        select(NotificationLog).where(
            NotificationLog.status == "queued",
            NotificationLog.channel == "email",
        ).order_by(NotificationLog.created_at.asc())
    )
    queued = result.scalars().all()

    sent = 0
    failed = 0
    skipped = 0

    for entry in queued:
        if not entry.subject or not entry.body:
            entry.status = "failed"
            entry.error_message = "Missing rendered subject or body"
            skipped += 1
            continue

        if not entry.recipient_email:
            entry.status = "failed"
            entry.error_message = "Missing recipient email"
            skipped += 1
            continue

        try:
            send_email(
                to_email=entry.recipient_email,
                subject=entry.subject,
                body=entry.body,
            )
            entry.status = "sent"
            entry.sent_at = datetime.now(timezone.utc)
            sent += 1
            logger.info("Email sent: id=%s to=%s subject=%s", entry.id, entry.recipient_email, entry.subject)
        except Exception as exc:
            entry.status = "failed"
            entry.error_message = str(exc)[:500]
            failed += 1
            logger.error("Email failed: id=%s to=%s error=%s", entry.id, entry.recipient_email, exc)

    await session.commit()

    summary = {"sent": sent, "failed": failed, "skipped": skipped}
    logger.info("Notification delivery complete: %s", summary)
    return summary
