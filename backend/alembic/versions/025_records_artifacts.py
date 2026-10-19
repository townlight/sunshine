"""Record prepared versus verified exports and fulfillment evidence."""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "025_records_artifacts"
down_revision = "024_records_file_evidence"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "request_artifacts",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("records_requests.id"), nullable=False),
        sa.Column("legacy_id", sa.Text()),
        *[sa.Column(name, sa.Text(), nullable=False) for name in ("kind", "content", "sha256", "response_sha256")],
        sa.Column("export_path", sa.Text(), unique=True),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        *[sa.Column(name, sa.Integer(), nullable=False) for name in ("document_count", "release_artifact_count", "search_session_count", "release_count", "redacted_count", "exempt_count")],
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.CheckConstraint("kind IN ('response','release-package')", name="records_artifact_kind"),
        sa.CheckConstraint("(completed_at IS NULL) = (export_path IS NULL)", name="records_artifact_completion"),
    )
    op.create_index("ix_request_artifacts_request_id", "request_artifacts", ["request_id"])
    op.create_table(
        "request_publications",
        sa.Column("id", UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", UUID(as_uuid=True), sa.ForeignKey("records_requests.id"), nullable=False),
        sa.Column("legacy_id", sa.Text()),
        sa.Column("payload", sa.Text(), nullable=False),
        sa.Column("payload_hash", sa.Text(), nullable=False),
        sa.Column("actor_id", UUID(as_uuid=True), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_request_publications_request_id", "request_publications", ["request_id"])


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM request_artifacts) OR EXISTS(SELECT 1 FROM request_publications)")):
        raise RuntimeError("Records artifact evidence exists; preserve it and repair forward.")
    op.drop_table("request_publications")
    op.drop_table("request_artifacts")
