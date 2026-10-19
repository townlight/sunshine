"""Lossless native Records intake/status/outbox mapping, not a second backend."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "022_native_records_mapping"
down_revision = "021_first_admin_rotate"
branch_labels = None
depends_on = None

_TEXT_FIELDS = ("requester_contact", "submitted_via", "deadline_label", "deadline_basis",
                "assigned_label", "fee_estimate_text", "fee_waiver_reason")
_TIMES = ("deadline_reviewed_at", "approved_at", "fulfilled_at")


def upgrade() -> None:
    # Native requester labels and local outbox strings were not bounded to the
    # old web column lengths. Widen; never truncate imported accepted content.
    op.alter_column("records_requests", "requester_name", type_=sa.Text())
    for name in ("desktop_id", "public_tracking_number", "display_status"):
        op.add_column("records_requests", sa.Column(name, sa.Text(), nullable=True))
    for name in _TEXT_FIELDS:
        op.add_column("records_requests", sa.Column(name, sa.Text(), nullable=False, server_default=""))
    for name in _TIMES:
        op.add_column("records_requests", sa.Column(name, sa.DateTime(timezone=True), nullable=True))
    op.add_column("records_requests", sa.Column("approved_response_sha256", sa.String(64), nullable=True))
    op.create_unique_constraint("uq_records_desktop_id", "records_requests", ["desktop_id"])
    op.create_unique_constraint("uq_records_tracking", "records_requests", ["public_tracking_number"])
    op.execute(sa.schema.CreateSequence(sa.Sequence("records_public_tracking_seq")))
    for name in ("legacy_id", "actor_label"):
        op.add_column("request_timeline", sa.Column(name, sa.Text(), nullable=True))
    op.create_table(
        "request_public_status",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True),
                  sa.ForeignKey("records_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("legacy_id", sa.Text(), nullable=True),
        sa.Column("label", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_public_status_request_id", "request_public_status", ["request_id"])
    for name in ("legacy_id", "module_id", "audience"):
        op.add_column("notification_log", sa.Column(name, sa.Text(), nullable=True))
    op.alter_column("notification_log", "channel", type_=sa.Text())
    op.alter_column("notification_log", "subject", type_=sa.Text())


def downgrade() -> None:
    # Refuse lossy narrowing rather than silently discard native history.
    connection = op.get_bind()
    oversize = connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM records_requests WHERE length(requester_name) > 255) "
        "OR EXISTS (SELECT 1 FROM notification_log WHERE length(channel) > 20 OR length(subject) > 500)"
    ))
    native = connection.scalar(sa.text(
        "SELECT EXISTS (SELECT 1 FROM records_requests WHERE desktop_id IS NOT NULL)"
    ))
    if oversize or native:
        raise RuntimeError("Native Records data requires a verified recovery point; downgrade would lose work.")
    for name in ("legacy_id", "module_id", "audience"):
        op.drop_column("notification_log", name)
    op.alter_column("notification_log", "channel", type_=sa.String(20))
    op.alter_column("notification_log", "subject", type_=sa.String(500))
    op.drop_table("request_public_status")
    for name in ("legacy_id", "actor_label"):
        op.drop_column("request_timeline", name)
    op.execute(sa.schema.DropSequence(sa.Sequence("records_public_tracking_seq")))
    op.drop_constraint("uq_records_desktop_id", "records_requests", type_="unique")
    op.drop_constraint("uq_records_tracking", "records_requests", type_="unique")
    for name in (*_TEXT_FIELDS, *_TIMES, "desktop_id", "public_tracking_number", "display_status",
                 "approved_response_sha256"):
        op.drop_column("records_requests", name)
    op.alter_column("records_requests", "requester_name", type_=sa.String(255))
