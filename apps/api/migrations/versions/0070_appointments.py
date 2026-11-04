"""Appointment booking.

``booking_settings`` holds each client's bookable hours and reminder, and
``appointments`` the times booked by agents or the team. Additive: two new
tables, nothing else moves."""
from alembic import op
import sqlalchemy as sa

revision = "0070_appointments"
down_revision = "0069_agent_test_cases"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "booking_settings",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("duration_minutes", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("slots", sa.JSON(), nullable=False),
        sa.Column("capacity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("min_notice_minutes", sa.Integer(), nullable=False, server_default="120"),
        sa.Column("max_days_ahead", sa.Integer(), nullable=False, server_default="30"),
        sa.Column("location", sa.Text(), nullable=False, server_default=""),
        sa.Column("reminder_enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("reminder_hours", sa.Integer(), nullable=False, server_default="24"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_booking_settings_agency_id", "booking_settings", ["agency_id"])
    op.create_table(
        "appointments",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("client_id", sa.Uuid(), sa.ForeignKey("clients.id", ondelete="CASCADE"), nullable=False),
        sa.Column("agent_id", sa.Uuid(), sa.ForeignKey("agents.id", ondelete="SET NULL"), nullable=True),
        sa.Column("conversation_id", sa.Uuid(), sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True),
        sa.Column("contact_id", sa.Uuid(), sa.ForeignKey("contacts.id", ondelete="SET NULL"), nullable=True),
        sa.Column("name", sa.String(180), nullable=False, server_default=""),
        sa.Column("phone", sa.String(40), nullable=False, server_default=""),
        sa.Column("notes", sa.Text(), nullable=False, server_default=""),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="confirmed"),
        sa.Column("source", sa.String(20), nullable=False, server_default="agent"),
        sa.Column("reminder_due_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_sent_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reminder_error", sa.String(300), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_appointments_agency_id", "appointments", ["agency_id"])
    op.create_index("ix_appointments_client_starts", "appointments", ["client_id", "starts_at"])
    op.create_index("ix_appointments_conversation_id", "appointments", ["conversation_id"])
    op.create_index("ix_appointments_contact_id", "appointments", ["contact_id"])
    op.create_index("ix_appointments_reminder_due_at", "appointments", ["reminder_due_at"])


def downgrade():
    for name in ("ix_appointments_reminder_due_at", "ix_appointments_contact_id", "ix_appointments_conversation_id",
                 "ix_appointments_client_starts", "ix_appointments_agency_id"):
        op.drop_index(name, table_name="appointments")
    op.drop_table("appointments")
    op.drop_index("ix_booking_settings_agency_id", table_name="booking_settings")
    op.drop_table("booking_settings")
