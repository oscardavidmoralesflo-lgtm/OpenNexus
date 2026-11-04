"""Ban shield for WhatsApp QR lines.

Adds the shield's settings and pause to ``whatsapp_channels`` and the
``whatsapp_send_events`` it counts. Additive: existing lines keep working,
with the shield on and their warm-up counted from when they were created."""
from alembic import op
import sqlalchemy as sa

revision = "0073_whatsapp_guard"
down_revision = "0072_campaigns"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("whatsapp_channels", sa.Column("guard_enabled", sa.Boolean(), nullable=False, server_default="true"))
    op.add_column("whatsapp_channels", sa.Column("warmup_started_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("whatsapp_channels", sa.Column("warmup_number", sa.String(80), nullable=True))
    # Numbers already linked are not new to WhatsApp: no warm-up for them.
    op.execute("UPDATE whatsapp_channels SET warmup_number = phone_number")
    op.add_column("whatsapp_channels", sa.Column("guard_paused_until", sa.DateTime(timezone=True), nullable=True))
    op.add_column("whatsapp_channels", sa.Column("guard_pause_reason", sa.String(300), nullable=True))
    op.create_table(
        "whatsapp_send_events",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("channel_id", sa.Uuid(), sa.ForeignKey("whatsapp_channels.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("text_hash", sa.String(64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_whatsapp_send_events_channel_time", "whatsapp_send_events", ["channel_id", "created_at"])


def downgrade():
    op.drop_index("ix_whatsapp_send_events_channel_time", table_name="whatsapp_send_events")
    op.drop_table("whatsapp_send_events")
    op.drop_column("whatsapp_channels", "guard_pause_reason")
    op.drop_column("whatsapp_channels", "guard_paused_until")
    op.drop_column("whatsapp_channels", "warmup_number")
    op.drop_column("whatsapp_channels", "warmup_started_at")
    op.drop_column("whatsapp_channels", "guard_enabled")
