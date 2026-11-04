"""The agency's own domain for the whole workspace, verified by a DNS TXT record."""
from alembic import op
import sqlalchemy as sa

revision = "0058_workspace_domain"
down_revision = "0057_conversation_summary"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agencies", sa.Column("workspace_domain", sa.String(255), nullable=True))
    op.add_column("agencies", sa.Column("workspace_domain_verified", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("agencies", sa.Column("workspace_domain_token", sa.String(64), nullable=False, server_default=""))
    op.create_unique_constraint("uq_agencies_workspace_domain", "agencies", ["workspace_domain"])


def downgrade():
    # contract: reviewed - the columns are new in this release; the previous
    # release never reads them, so dropping them loses only this feature's setup.
    op.drop_constraint("uq_agencies_workspace_domain", "agencies", type_="unique")
    op.drop_column("agencies", "workspace_domain_token")
    op.drop_column("agencies", "workspace_domain_verified")
    op.drop_column("agencies", "workspace_domain")
