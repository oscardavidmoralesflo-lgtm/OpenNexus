"""Agent quality lab.

``agent_test_cases`` holds the questions an agency checks each agent with,
and the latest verdict. Additive: a new table, nothing else moves."""
from alembic import op
import sqlalchemy as sa

revision = "0069_agent_test_cases"
down_revision = "0068_audit_events"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "agent_test_cases",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("expectation", sa.Text(), nullable=False, server_default=""),
        sa.Column("last_answer", sa.Text(), nullable=True),
        sa.Column("last_passed", sa.Boolean(), nullable=True),
        sa.Column("last_score", sa.Integer(), nullable=True),
        sa.Column("last_reason", sa.Text(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_test_cases_agency_id", "agent_test_cases", ["agency_id"])
    op.create_index("ix_agent_test_cases_agent_id", "agent_test_cases", ["agent_id"])


def downgrade():
    op.drop_index("ix_agent_test_cases_agent_id", table_name="agent_test_cases")
    op.drop_index("ix_agent_test_cases_agency_id", table_name="agent_test_cases")
    op.drop_table("agent_test_cases")
