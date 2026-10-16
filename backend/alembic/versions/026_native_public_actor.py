"""Represent anonymous native public intake honestly, without an invented admin."""
from alembic import op
import sqlalchemy as sa

revision = "026_native_public_actor"
down_revision = "025_records_artifacts"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("records_requests", "created_by", nullable=True)


def downgrade():
    if op.get_bind().scalar(sa.text("SELECT EXISTS(SELECT 1 FROM records_requests WHERE created_by IS NULL)")):
        raise RuntimeError("Anonymous native intake exists; do not invent a historical actor.")
    op.alter_column("records_requests", "created_by", nullable=False)
