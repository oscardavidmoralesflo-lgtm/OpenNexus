"""Audit log.

``audit_events`` keeps one row per change made in the dashboard and per
sign-in, scoped to the agency. Additive: a new table, nothing else moves."""
from alembic import op
import sqlalchemy as sa

revision = "0068_audit_events"
down_revision = "0067_phone_calls"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("actor_email", sa.String(320), nullable=False, server_default=""),
        sa.Column("action", sa.String(120), nullable=False),
        sa.Column("method", sa.String(10), nullable=False, server_default=""),
        sa.Column("path", sa.String(500), nullable=False, server_default=""),
        sa.Column("status_code", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("target_id", sa.String(64), nullable=True),
        sa.Column("ip", sa.String(64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(300), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_audit_events_agency_created", "audit_events", ["agency_id", "created_at"])


def downgrade():
    op.drop_index("ix_audit_events_agency_created", table_name="audit_events")
    op.drop_table("audit_events")
