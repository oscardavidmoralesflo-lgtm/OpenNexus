"""WhatsApp campaigns.

``campaigns`` holds each broadcast (template, audience, schedule, status)
and ``campaign_recipients`` every contact it goes to with the outcome.
Additive: two new tables."""
from alembic import op
import sqlalchemy as sa

revision = "0072_campaigns"
down_revision = "0071_sales_pipeline"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "campaigns",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("whatsapp_cloud_channel_id", sa.Uuid(), sa.ForeignKey("whatsapp_cloud_channels.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("template_name", sa.String(512), nullable=False),
        sa.Column("template_language", sa.String(10), nullable=False),
        sa.Column("variables", sa.JSON(), nullable=False),
        sa.Column("header_value", sa.Text(), nullable=False, server_default=""),
        sa.Column("audience", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="draft"),
        sa.Column("scheduled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_campaigns_agency_id", "campaigns", ["agency_id"])
    op.create_index("ix_campaigns_client_id", "campaigns", ["client_id"])
    op.create_index("ix_campaigns_scheduled_at", "campaigns", ["scheduled_at"])
    op.create_table(
        "campaign_recipients",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("campaign_id", sa.Uuid(), sa.ForeignKey("campaigns.id", ondelete="CASCADE"), nullable=False),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("phone", sa.String(40), nullable=False),
        sa.Column("name", sa.String(180), nullable=False, server_default=""),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("error", sa.String(300), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("message_id", sa.Uuid(), sa.ForeignKey("messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("campaign_id", "contact_id", name="uq_campaign_recipients_contact"),
    )
    op.create_index("ix_campaign_recipients_campaign_id", "campaign_recipients", ["campaign_id"])


def downgrade():
    op.drop_index("ix_campaign_recipients_campaign_id", table_name="campaign_recipients")
    op.drop_table("campaign_recipients")
    for name in ("ix_campaigns_scheduled_at", "ix_campaigns_client_id", "ix_campaigns_agency_id"):
        op.drop_index(name, table_name="campaigns")
    op.drop_table("campaigns")
