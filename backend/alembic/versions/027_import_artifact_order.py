"""Preserve legacy artifact ordering when timestamps have one-second precision."""
from alembic import op
import sqlalchemy as sa

revision = "027_import_artifact_order"
down_revision = "026_native_public_actor"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("request_artifacts", sa.Column("position", sa.Integer(), nullable=True))


def downgrade():
    op.drop_column("request_artifacts", "position")
