"""Store document sizes beyond the PostgreSQL integer range.

Revision ID: 028_document_file_size_bigint
Revises: 027_import_artifact_order
"""
from alembic import op
import sqlalchemy as sa


revision = "028_document_file_size_bigint"
down_revision = "027_import_artifact_order"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "documents",
        "file_size",
        existing_type=sa.Integer(),
        type_=sa.BigInteger(),
        existing_nullable=False,
        existing_server_default="0",
    )


def downgrade() -> None:
    # PostgreSQL performs the int8 -> int4 rewrite transactionally and aborts
    # if any value is out of int4 range; the rollback retains all data, so no
    # truncation is performed here.
    op.alter_column(
        "documents",
        "file_size",
        existing_type=sa.BigInteger(),
        type_=sa.Integer(),
        existing_nullable=False,
        existing_server_default="0",
    )
