"""Lossless accepted Records lifecycle evidence, not a second state blob."""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "023_native_records_lifecycle"
down_revision = "022_native_records_mapping"
branch_labels = None
depends_on = None


def upgrade():
    for table in ("request_timeline", "request_public_status", "request_messages"):
        op.add_column(table, sa.Column("position", sa.Integer(), nullable=True))
    for column in ("legacy_id", "sender_label"):
        op.add_column("request_messages", sa.Column(column, sa.Text(), nullable=True))
    op.create_table(
        "request_evidence_notes",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("records_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('clarification','search','exemption','citation','approval','export')", name="records_evidence_note_kind"),
    )
    op.create_index("ix_request_evidence_notes_request_id", "request_evidence_notes", ["request_id"])
    op.create_table(
        "request_exemption_decisions",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("records_requests.id", ondelete="CASCADE"), nullable=False),
        sa.Column("flag_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("exemption_flags.id")),
        sa.Column("legacy_id", sa.Text()), sa.Column("position", sa.Integer(), nullable=False),
        *[sa.Column(column, sa.Text(), nullable=False) for column in
          ("source", "kind", "finding", "decision", "basis", "reviewer_label")],
        sa.Column("actor_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("users.id", ondelete="SET NULL")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("decision IN ('release','redact','exempt')", name="records_segment_decision"),
    )
    op.create_index("ix_request_exemption_decisions_request_id", "request_exemption_decisions", ["request_id"])
    op.add_column("search_queries", sa.Column("request_id", postgresql.UUID(as_uuid=True), sa.ForeignKey("records_requests.id")))
    op.create_index("ix_search_queries_request_id", "search_queries", ["request_id"])
    op.add_column("search_queries", sa.Column("position", sa.Integer()))
    for column in ("legacy_id", "locations", "reviewer_label"):
        op.add_column("search_queries", sa.Column(column, sa.Text()))
    op.alter_column("search_results", "chunk_id", nullable=True)
    op.alter_column("search_results", "similarity_score", nullable=True)
    for column in ("legacy_id", "title", "citation", "summary", "review_status"):
        op.add_column("search_results", sa.Column(column, sa.Text()))
    op.add_column("fee_line_items", sa.Column("legacy_id", sa.Text()))
    op.add_column("fee_line_items", sa.Column("position", sa.Integer()))
    op.add_column("fee_line_items", sa.Column("schedule_basis", sa.Text(), nullable=False, server_default=""))
    op.alter_column("fee_line_items", "description", type_=sa.Text())
    op.alter_column("fee_waivers", "reason", type_=sa.Text())
    for table, column in (("fee_line_items", "unit_price"), ("fee_line_items", "total"), ("records_requests", "estimated_fee")):
        op.alter_column(table, column, type_=sa.Numeric(21, 2))


def downgrade():
    connection = op.get_bind()
    # A downgrade must not silently discard imported or newly accepted work.
    evidence = connection.scalar(sa.text("""
        SELECT EXISTS(SELECT 1 FROM request_evidence_notes)
          OR EXISTS(SELECT 1 FROM request_exemption_decisions)
          OR EXISTS(SELECT 1 FROM search_queries WHERE request_id IS NOT NULL)
          OR EXISTS(SELECT 1 FROM fee_line_items WHERE legacy_id IS NOT NULL OR schedule_basis <> ''
                    OR length(description) > 500 OR abs(unit_price) >= 100000000 OR abs(total) >= 100000000)
          OR EXISTS(SELECT 1 FROM records_requests WHERE abs(estimated_fee) >= 100000000)
          OR EXISTS(SELECT 1 FROM fee_waivers WHERE length(reason) > 2000)
          OR EXISTS(SELECT 1 FROM request_messages WHERE legacy_id IS NOT NULL OR sender_label IS NOT NULL)
    """))
    if evidence:
        raise RuntimeError("Records lifecycle evidence exists; preserve current SQL and repair forward instead of a lossy downgrade.")
    op.drop_table("request_exemption_decisions")
    op.drop_table("request_evidence_notes")
    for table in ("request_timeline", "request_public_status", "request_messages"):
        op.drop_column(table, "position")
    for column in ("legacy_id", "sender_label"):
        op.drop_column("request_messages", column)
    for column in ("request_id", "legacy_id", "position", "locations", "reviewer_label"):
        op.drop_column("search_queries", column)
    for column in ("legacy_id", "title", "citation", "summary", "review_status"):
        op.drop_column("search_results", column)
    op.alter_column("search_results", "chunk_id", nullable=False)
    op.alter_column("search_results", "similarity_score", nullable=False)
    for column in ("legacy_id", "position", "schedule_basis"):
        op.drop_column("fee_line_items", column)
    op.alter_column("fee_line_items", "description", type_=sa.String(500))
    op.alter_column("fee_waivers", "reason", type_=sa.String(2000))
    for table, column in (("fee_line_items", "unit_price"), ("fee_line_items", "total"), ("records_requests", "estimated_fee")):
        op.alter_column(table, column, type_=sa.Numeric(10, 2))
