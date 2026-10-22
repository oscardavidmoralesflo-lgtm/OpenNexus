"""Track per-agent managed account connections, without storing OAuth tokens."""
from alembic import op
import sqlalchemy as sa

revision = "0064_managed_integrations"
down_revision = "0063_agent_humanization"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "managed_integrations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("toolkit", sa.String(100), nullable=False),
        sa.Column("auth_config_id", sa.String(180), nullable=False),
        sa.Column("account_id", sa.String(180), nullable=False),
        sa.Column("status", sa.String(30), nullable=False),
        sa.Column("tool_id", sa.Uuid(), sa.ForeignKey("agent_tools.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("agent_id", "toolkit", name="uq_managed_integrations_agent_toolkit"),
    )
    op.create_index("ix_managed_integrations_agent_id", "managed_integrations", ["agent_id"])


def downgrade():
    # contract: reviewed - removes only connections introduced by this release;
    # account grants remain manageable at the external service.
    op.drop_table("managed_integrations")
