"""Personal tokens for external AI agents over MCP, and the log of their tool calls."""
from alembic import op
import sqlalchemy as sa

revision = "0059_mcp_tokens"
down_revision = "0058_workspace_domain"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mcp_tokens",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("prefix", sa.String(16), nullable=False),
        sa.Column("read_only", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("token_hash", name="uq_mcp_tokens_token_hash"),
    )
    op.create_index("ix_mcp_tokens_agency_id", "mcp_tokens", ["agency_id"])
    op.create_index("ix_mcp_tokens_user_id", "mcp_tokens", ["user_id"])
    op.create_table(
        "mcp_activity",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("token_id", sa.Uuid(), sa.ForeignKey("mcp_tokens.id", ondelete="SET NULL"), nullable=True),
        sa.Column("tool", sa.String(80), nullable=False),
        sa.Column("ok", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("arguments", sa.JSON(), nullable=False, server_default="{}"),
        sa.Column("summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_mcp_activity_agency_created", "mcp_activity", ["agency_id", "created_at"])
    op.create_index("ix_mcp_activity_token_id", "mcp_activity", ["token_id"])


def downgrade():
    # contract: reviewed - both tables are new in this release and nothing in
    # the previous release reads them; dropping them only removes MCP access.
    op.drop_index("ix_mcp_activity_token_id", table_name="mcp_activity")
    op.drop_index("ix_mcp_activity_agency_created", table_name="mcp_activity")
    op.drop_table("mcp_activity")
    op.drop_index("ix_mcp_tokens_user_id", table_name="mcp_tokens")
    op.drop_index("ix_mcp_tokens_agency_id", table_name="mcp_tokens")
    op.drop_table("mcp_tokens")
