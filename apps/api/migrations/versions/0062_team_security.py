"""Agency team: roles, invitations, and two-step verification."""
from alembic import op
import sqlalchemy as sa

revision = "0062_team_security"
down_revision = "0061_billing"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agencies", sa.Column("require_two_factor", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("totp_secret", sa.Text(), nullable=True))
    op.add_column("users", sa.Column("totp_enabled", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("users", sa.Column("totp_last_step", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("recovery_codes", sa.JSON(), nullable=False, server_default="[]"))
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(timezone=True), nullable=True))
    # Until now every agency user was its owner, stored as "admin".
    op.execute("UPDATE users SET role = 'owner' WHERE role = 'admin'")
    op.create_table(
        "invitations",
        sa.Column("id", sa.Uuid(), primary_key=True),
        sa.Column("agency_id", sa.Uuid(), sa.ForeignKey("agencies.id", ondelete="CASCADE"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(30), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("invited_by_id", sa.Uuid(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_invitations_token_hash"),
    )
    op.create_index("ix_invitations_agency_id", "invitations", ["agency_id"])


def downgrade():
    # contract: reviewed - new in this release. Going back loses invitations and
    # two-step setups; owners become "admin" again, which the previous release
    # treats as the agency's owner.
    op.drop_index("ix_invitations_agency_id", table_name="invitations")
    op.drop_table("invitations")
    op.execute("UPDATE users SET role = 'admin' WHERE role = 'owner'")
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "recovery_codes")
    op.drop_column("users", "totp_last_step")
    op.drop_column("users", "totp_enabled")
    op.drop_column("users", "totp_secret")
    op.drop_column("agencies", "require_two_factor")
