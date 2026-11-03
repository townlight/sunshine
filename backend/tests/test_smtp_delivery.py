"""Tests for SMTP notification delivery."""

from unittest.mock import patch, MagicMock

import pytest
from httpx import AsyncClient

from townlight_records.notifications.smtp_delivery import send_email, deliver_queued_notifications


def test_send_email_raises_without_smtp_host():
    """send_email fails if SMTP_HOST is not configured."""
    with patch("townlight_records.notifications.smtp_delivery.settings") as mock_settings:
        mock_settings.smtp_host = ""
        with pytest.raises(RuntimeError, match="SMTP_HOST not configured"):
            send_email("test@city.gov", "Test Subject", "Test Body")


def test_send_email_connects_and_sends():
    """send_email creates SMTP connection, logs in, and sends."""
    with patch("townlight_records.notifications.smtp_delivery.settings") as mock_settings, \
         patch("townlight_records.notifications.smtp_delivery.smtplib.SMTP") as mock_smtp_class:
        mock_settings.smtp_host = "smtp.city.gov"
        mock_settings.smtp_port = 587
        mock_settings.smtp_username = "user"
        mock_settings.smtp_password = "pass"
        mock_settings.smtp_from_email = "noreply@city.gov"
        mock_settings.smtp_use_tls = True

        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        send_email("clerk@city.gov", "Test Subject", "Test Body")

        mock_smtp_class.assert_called_once_with("smtp.city.gov", 587)
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once_with("user", "pass")
        mock_server.sendmail.assert_called_once()
        mock_server.quit.assert_called_once()

        # Verify the email content
        call_args = mock_server.sendmail.call_args
        assert call_args[0][0] == "noreply@city.gov"  # from
        assert call_args[0][1] == ["clerk@city.gov"]  # to


def test_send_email_without_tls():
    """send_email works without TLS."""
    with patch("townlight_records.notifications.smtp_delivery.settings") as mock_settings, \
         patch("townlight_records.notifications.smtp_delivery.smtplib.SMTP") as mock_smtp_class:
        mock_settings.smtp_host = "smtp.city.gov"
        mock_settings.smtp_port = 25
        mock_settings.smtp_username = ""
        mock_settings.smtp_password = ""
        mock_settings.smtp_from_email = "noreply@city.gov"
        mock_settings.smtp_use_tls = False

        mock_server = MagicMock()
        mock_smtp_class.return_value = mock_server

        send_email("clerk@city.gov", "Subject", "Body")

        mock_server.starttls.assert_not_called()
        mock_server.login.assert_not_called()
        mock_server.sendmail.assert_called_once()


@pytest.mark.asyncio
async def test_deliver_skips_when_smtp_not_configured(client: AsyncClient):
    """deliver_queued_notifications returns early if SMTP not configured."""
    from tests.conftest import test_session_maker

    with patch("townlight_records.notifications.smtp_delivery.settings") as mock_settings:
        mock_settings.smtp_host = ""
        async with test_session_maker() as session:
            result = await deliver_queued_notifications(session)
            assert result["reason"] == "smtp_not_configured"
            assert result["sent"] == 0


@pytest.mark.asyncio
async def test_deliver_sends_queued_email(client: AsyncClient):
    """deliver_queued_notifications processes queued entries."""
    from tests.conftest import test_session_maker
    from townlight_records.models.notifications import NotificationLog

    async with test_session_maker() as session:
        # Create a queued notification
        log = NotificationLog(
            recipient_email="clerk@city.gov",
            channel="email",
            subject="Test Subject",
            body="Test Body",
            status="queued",
        )
        session.add(log)
        await session.commit()
        log_id = log.id

    with patch("townlight_records.notifications.smtp_delivery.settings") as mock_settings, \
         patch("townlight_records.notifications.smtp_delivery.send_email") as mock_send:
        mock_settings.smtp_host = "smtp.city.gov"

        async with test_session_maker() as session:
            result = await deliver_queued_notifications(session)

        assert result["sent"] == 1
        mock_send.assert_called_once_with(
            to_email="clerk@city.gov",
            subject="Test Subject",
            body="Test Body",
        )

    # Verify status updated
    async with test_session_maker() as session:
        entry = await session.get(NotificationLog, log_id)
        assert entry.status == "sent"
        assert entry.sent_at is not None


@pytest.mark.asyncio
async def test_deliver_handles_smtp_failure(client: AsyncClient):
    """deliver_queued_notifications marks entries as failed on SMTP error."""
    from tests.conftest import test_session_maker
    from townlight_records.models.notifications import NotificationLog

    async with test_session_maker() as session:
        log = NotificationLog(
            recipient_email="clerk@city.gov",
            channel="email",
            subject="Fail Test",
            body="Body",
            status="queued",
        )
        session.add(log)
        await session.commit()
        log_id = log.id

    with patch("townlight_records.notifications.smtp_delivery.settings") as mock_settings, \
         patch("townlight_records.notifications.smtp_delivery.send_email", side_effect=Exception("Connection refused")):
        mock_settings.smtp_host = "smtp.city.gov"

        async with test_session_maker() as session:
            result = await deliver_queued_notifications(session)

        assert result["failed"] == 1

    async with test_session_maker() as session:
        entry = await session.get(NotificationLog, log_id)
        assert entry.status == "failed"
        assert "Connection refused" in entry.error_message
