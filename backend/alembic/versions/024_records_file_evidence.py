"""Preserve original attachments and immutable release-copy history."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "024_records_file_evidence"
down_revision = "023_native_records_lifecycle"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_file_evidence",
        sa.Column("id", UUID(as_uuid=True), sa.ForeignKey("request_documents.id"), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("records_requests.id"), nullable=False),
        sa.Column("legacy_id", sa.Text()),
        sa.Column("position", sa.Integer(), nullable=False),
        *[sa.Column(name, sa.Text(), nullable=False) for name in ("title", "original_path", "citation", "added_by")],
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_file_evidence_request_id", "request_file_evidence", ["request_id"])
    op.create_table(
        "request_release_copies",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("records_requests.id"), nullable=False),
        sa.Column("attachment_id", UUID(as_uuid=True), sa.ForeignKey("request_file_evidence.id"), nullable=False),
        *[sa.Column(name, sa.Text(), nullable=False) for name in
          ("original_path", "stored_path", "file_name", "sha256", "status", "note", "added_by")],
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("stored_path"),
        sa.CheckConstraint("status IN ('release-ready copy','redacted copy')", name="records_release_copy_status"),
    )
    op.create_index("ix_request_release_copies_request_id", "request_release_copies", ["request_id"])
    op.create_index("ix_request_release_copies_attachment_id", "request_release_copies", ["attachment_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM request_file_evidence) OR EXISTS(SELECT 1 FROM request_release_copies)")):
        raise RuntimeError("Records file evidence exists; preserve it and repair forward.")
    op.drop_table("request_release_copies")
    op.drop_table("request_file_evidence")
