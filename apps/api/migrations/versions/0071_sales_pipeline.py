"""Sales pipeline.

Contacts gain a pipeline stage, when it last changed and the deal's value;
clients gain the switch that lets agents move contacts through it. Additive:
new nullable columns and a default-off flag."""
from alembic import op
import sqlalchemy as sa

revision = "0071_sales_pipeline"
down_revision = "0070_appointments"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("contacts", sa.Column("stage", sa.String(20), nullable=True))
    op.add_column("contacts", sa.Column("stage_changed_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("contacts", sa.Column("deal_value", sa.Numeric(14, 2), nullable=True))
    op.add_column("clients", sa.Column("pipeline_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade():
    op.drop_column("clients", "pipeline_enabled")
    op.drop_column("contacts", "deal_value")
    op.drop_column("contacts", "stage_changed_at")
    op.drop_column("contacts", "stage")
