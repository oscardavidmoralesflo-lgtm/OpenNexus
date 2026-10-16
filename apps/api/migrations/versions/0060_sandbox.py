"""The sandbox: a flagged client, a code per agent, and which agent each chat talks to."""
from alembic import op
import sqlalchemy as sa

revision = "0060_sandbox"
down_revision = "0059_mcp_tokens"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("clients", sa.Column("is_sandbox", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("agents", sa.Column("sandbox_code", sa.String(16), nullable=True))
    op.create_index("ix_agents_sandbox_code", "agents", ["sandbox_code"])
    op.create_table(
        "sandbox_sessions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("external_chat_id", sa.String(255), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("client_id", "external_chat_id", name="uq_sandbox_sessions_chat"),
    )
    op.create_index("ix_sandbox_sessions_client_id", "sandbox_sessions", ["client_id"])
    op.create_index("ix_sandbox_sessions_agent_id", "sandbox_sessions", ["agent_id"])


def downgrade():
    # contract: reviewed - everything here is new in this release; the previous
    # release ignores the sandbox client, which keeps working as a plain client.
    op.drop_index("ix_sandbox_sessions_agent_id", table_name="sandbox_sessions")
    op.drop_index("ix_sandbox_sessions_client_id", table_name="sandbox_sessions")
    op.drop_table("sandbox_sessions")
    op.drop_index("ix_agents_sandbox_code", table_name="agents")
    op.drop_column("agents", "sandbox_code")
    op.drop_column("clients", "is_sandbox")
