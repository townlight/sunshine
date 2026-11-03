"""IMAP Email Connector — ingests emails and attachments from a mail server.

Security considerations (per audit guidance):
- Emails from external senders are the highest-risk input path
- MIME type allowlist rejects executables and unknown types
- File size ceiling prevents resource exhaustion
- Only ingestion-safe file types are accepted
- All content eventually passes through sanitize_for_llm() at the chunking stage
"""

import asyncio
import email
import email.policy
import imaplib
import logging
import time

from townlight_records.connectors.base import (
    BaseConnector,
    DiscoveredRecord,
    FetchedDocument,
    HealthCheckResult,
    HealthStatus,
)

logger = logging.getLogger(__name__)

# ── Attachment Sanitization ───────────────────────────────────────────────────

# Only these MIME types are allowed through to ingestion
ALLOWED_MIME_TYPES = frozenset({
    # Documents
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",  # DOCX
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",  # XLSX
    "application/msword",  # DOC
    "application/vnd.ms-excel",  # XLS
    "text/plain",
    "text/html",
    "text/csv",
    # Images (for multimodal ingestion)
    "image/jpeg",
    "image/png",
    "image/tiff",
    # Email
    "message/rfc822",  # forwarded emails
})

# File extensions that are always rejected regardless of MIME type
BLOCKED_EXTENSIONS = frozenset({
    ".exe", ".bat", ".cmd", ".com", ".msi", ".scr", ".pif",
    ".vbs", ".vbe", ".js", ".jse", ".wsf", ".wsh", ".ps1",
    ".dll", ".sys", ".drv", ".ocx", ".cpl",
    ".jar", ".class", ".py", ".rb", ".sh", ".bash",
    ".zip", ".rar", ".7z", ".tar", ".gz",  # archives could contain anything
    ".iso", ".img", ".dmg",
})

# Max attachment size: 50 MB
MAX_ATTACHMENT_BYTES = 50 * 1024 * 1024


def is_attachment_safe(filename: str | None, content_type: str, size: int) -> tuple[bool, str]:
    """Check if an email attachment is safe for ingestion.

    Returns (is_safe, reason) tuple.
    """
    if not filename:
        return False, "No filename"

    # Check extension
    ext = "." + filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if ext in BLOCKED_EXTENSIONS:
        return False, f"Blocked extension: {ext}"

    # Check MIME type
    base_type = content_type.split(";")[0].strip().lower()
    if base_type not in ALLOWED_MIME_TYPES:
        return False, f"Disallowed MIME type: {base_type}"

    # Check size
    if size > MAX_ATTACHMENT_BYTES:
        return False, f"Too large: {size / 1024 / 1024:.1f} MB (max {MAX_ATTACHMENT_BYTES / 1024 / 1024:.0f} MB)"

    return True, "OK"


# ── IMAP Connector ────────────────────────────────────────────────────────────

class ImapEmailConnector(BaseConnector):
    """Connector for IMAP email servers.

    Config keys:
        host: IMAP server hostname
        port: IMAP port (default 993 for SSL)
        username: Login username
        password: Login password
        use_ssl: Use SSL connection (default True)
        folder: Mailbox folder to read (default "INBOX")
        max_emails: Maximum emails to discover per run (default 100)
    """

    def __init__(self, config: dict):
        super().__init__(config)
        self._conn: imaplib.IMAP4_SSL | imaplib.IMAP4 | None = None

    @property
    def connector_type(self) -> str:
        return "imap_email"

    def _authenticate_sync(self) -> bool:
        """Blocking IMAP connect + login. Called via asyncio.to_thread()."""
        host = self.config.get("host", "")
        port = self.config.get("port", 993)
        username = self.config.get("username", "")
        password = self.config.get("password", "")
        use_ssl = self.config.get("use_ssl", True)

        if not host or not username or not password:
            logger.error("IMAP config missing host, username, or password")
            return False

        try:
            if use_ssl:
                self._conn = imaplib.IMAP4_SSL(host, port)
            else:
                self._conn = imaplib.IMAP4(host, port)

            self._conn.login(username, password)
            self._authenticated = True
            logger.info("IMAP authenticated: %s@%s:%d", username, host, port)
            return True
        except imaplib.IMAP4.error as exc:
            logger.error("IMAP authentication failed: %s", exc)
            self._authenticated = False
            return False

    async def authenticate(self) -> bool:
        """Connect and authenticate to the IMAP server (non-blocking)."""
        return await asyncio.to_thread(self._authenticate_sync)

    def _discover_sync(self) -> list[DiscoveredRecord]:
        """Blocking IMAP mailbox listing. Called via asyncio.to_thread()."""
        if not self._conn or not self._authenticated:
            raise RuntimeError("Not authenticated — call authenticate() first")

        folder = self.config.get("folder", "INBOX")
        max_emails = self.config.get("max_emails", 100)

        self._conn.select(folder, readonly=True)
        _, data = self._conn.search(None, "ALL")
        message_ids = data[0].split()

        recent_ids = message_ids[-max_emails:] if len(message_ids) > max_emails else message_ids

        records = []
        for msg_id in recent_ids:
            _, msg_data = self._conn.fetch(msg_id, "(RFC822.SIZE BODY[HEADER.FIELDS (SUBJECT FROM DATE)])")
            if not msg_data or not msg_data[0]:
                continue

            header_bytes = msg_data[0][1] if isinstance(msg_data[0], tuple) else b""
            header = email.message_from_bytes(header_bytes, policy=email.policy.default)

            subject = str(header.get("Subject", "No Subject"))
            from_addr = str(header.get("From", "Unknown"))
            date_str = str(header.get("Date", ""))

            size_info = msg_data[0][0] if isinstance(msg_data[0], tuple) else b""
            size = 0
            if b"RFC822.SIZE" in size_info:
                try:
                    size = int(size_info.decode().split("RFC822.SIZE")[1].split(")")[0].strip())
                except (ValueError, IndexError):
                    pass

            records.append(DiscoveredRecord(
                source_path=f"imap://{folder}/{msg_id.decode()}",
                filename=f"{subject[:80]}.eml",
                file_type="message/rfc822",
                file_size=size,
                last_modified=None,
                metadata={
                    "subject": subject,
                    "from": from_addr,
                    "date": date_str,
                    "message_id": msg_id.decode(),
                    "folder": folder,
                },
            ))

        logger.info("IMAP discover: %d emails found in %s", len(records), folder)
        return records

    async def discover(self) -> list[DiscoveredRecord]:
        """List emails in the configured mailbox folder (non-blocking)."""
        return await asyncio.to_thread(self._discover_sync)

    def _fetch_sync(self, source_path: str) -> FetchedDocument:
        """Blocking IMAP message fetch. Called via asyncio.to_thread()."""
        if not self._conn or not self._authenticated:
            raise RuntimeError("Not authenticated — call authenticate() first")

        parts = source_path.replace("imap://", "").split("/", 1)
        folder = parts[0] if len(parts) > 1 else "INBOX"
        msg_id = parts[-1]

        self._conn.select(folder, readonly=True)
        _, msg_data = self._conn.fetch(msg_id.encode(), "(RFC822)")

        if not msg_data or not msg_data[0]:
            raise FileNotFoundError(f"Email not found: {source_path}")

        raw_email = msg_data[0][1]
        parsed = email.message_from_bytes(raw_email, policy=email.policy.default)

        subject = str(parsed.get("Subject", "No Subject"))

        return FetchedDocument(
            source_path=source_path,
            filename=f"{subject[:80]}.eml",
            file_type="message/rfc822",
            content=raw_email,
            file_size=len(raw_email),
            metadata={
                "subject": subject,
                "from": str(parsed.get("From", "")),
                "to": str(parsed.get("To", "")),
                "date": str(parsed.get("Date", "")),
            },
        )

    async def fetch(self, source_path: str) -> FetchedDocument:
        """Fetch a specific email by message ID (non-blocking)."""
        return await asyncio.to_thread(self._fetch_sync, source_path)

    def _health_check_sync(self) -> HealthCheckResult:
        """Blocking IMAP NOOP check. Called via asyncio.to_thread()."""
        if not self._conn:
            return HealthCheckResult(
                status=HealthStatus.UNREACHABLE,
                error_message="Not connected",
            )

        start = time.monotonic()
        try:
            self._conn.noop()
            latency = int((time.monotonic() - start) * 1000)
            return HealthCheckResult(
                status=HealthStatus.HEALTHY,
                latency_ms=latency,
            )
        except Exception as exc:
            return HealthCheckResult(
                status=HealthStatus.FAILED,
                error_message=str(exc),
            )

    async def health_check(self) -> HealthCheckResult:
        """Check IMAP connection health (non-blocking)."""
        if not self._conn:
            return HealthCheckResult(
                status=HealthStatus.UNREACHABLE,
                error_message="Not connected",
            )
        return await asyncio.to_thread(self._health_check_sync)

    def extract_safe_attachments(self, raw_email: bytes) -> list[FetchedDocument]:
        """Extract attachments from a raw email, applying safety filters.

        Only attachments that pass the MIME type allowlist, extension blocklist,
        and size check are returned. Rejected attachments are logged.
        """
        parsed = email.message_from_bytes(raw_email, policy=email.policy.default)
        attachments = []
        rejected = 0

        for part in parsed.walk():
            content_disposition = str(part.get("Content-Disposition", ""))
            if "attachment" not in content_disposition and part.get_content_maintype() == "multipart":
                continue

            filename = part.get_filename()
            if not filename:
                continue

            content_type = part.get_content_type()
            payload = part.get_payload(decode=True)
            if payload is None:
                continue

            safe, reason = is_attachment_safe(filename, content_type, len(payload))
            if not safe:
                logger.warning(
                    "Rejected attachment: %s (%s) — %s",
                    filename, content_type, reason,
                )
                rejected += 1
                continue

            # Map MIME type to simple file type for ingestion
            ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else "bin"

            attachments.append(FetchedDocument(
                source_path=f"attachment://{filename}",
                filename=filename,
                file_type=ext,
                content=payload,
                file_size=len(payload),
                metadata={
                    "content_type": content_type,
                    "email_subject": str(parsed.get("Subject", "")),
                    "email_from": str(parsed.get("From", "")),
                },
            ))

        if rejected:
            logger.info(
                "Attachment filter: %d accepted, %d rejected from email",
                len(attachments), rejected,
            )

        return attachments
