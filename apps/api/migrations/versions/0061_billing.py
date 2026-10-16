"""Plans, subscription state and AI credit for deployments that bill their agency."""
from alembic import op
import sqlalchemy as sa

revision = "0061_billing"
down_revision = "0060_sandbox"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agencies", sa.Column("plan", sa.String(40), nullable=False, server_default=""))
    op.add_column("agencies", sa.Column("subscription_status", sa.String(30), nullable=False, server_default="none"))
    op.add_column("agencies", sa.Column("stripe_customer_id", sa.String(80), nullable=True))
    op.add_column("agencies", sa.Column("stripe_subscription_id", sa.String(80), nullable=True))
    op.add_column("agencies", sa.Column("credit_balance", sa.Numeric(14, 6), nullable=False, server_default="0"))
    op.create_table(
        "credit_transactions",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("amount_usd", sa.Numeric(14, 6), nullable=False),
        sa.Column("balance_after", sa.Numeric(14, 6), nullable=False),
        sa.Column("description", sa.String(240), nullable=False, server_default=""),
        sa.Column("reference", sa.String(120), nullable=True),
        sa.Column("usage_record_id", sa.Uuid(), sa.ForeignKey("usage_records.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("kind", "reference", name="uq_credit_transactions_reference"),
    )
    op.create_index("ix_credit_transactions_agency_created", "credit_transactions", ["agency_id", "created_at"])
    op.create_index("ix_credit_transactions_usage_record_id", "credit_transactions", ["usage_record_id"])


def downgrade():
    # contract: reviewed - all new in this release. Dropping them loses the
    # credit ledger and balance, so export them first if billing was in use.
    op.drop_index("ix_credit_transactions_usage_record_id", table_name="credit_transactions")
    op.drop_index("ix_credit_transactions_agency_created", table_name="credit_transactions")
    op.drop_table("credit_transactions")
    op.drop_column("agencies", "credit_balance")
    op.drop_column("agencies", "stripe_subscription_id")
    op.drop_column("agencies", "stripe_customer_id")
    op.drop_column("agencies", "subscription_status")
    op.drop_column("agencies", "plan")
