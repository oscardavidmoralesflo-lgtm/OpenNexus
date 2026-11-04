"""Humanized delivery per agent: split replies, typing pace, style mirroring and voice notes."""
from alembic import op
import sqlalchemy as sa

revision = "0063_agent_humanization"
down_revision = "0062_team_security"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("agents", sa.Column("split_replies", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("agents", sa.Column("split_max_parts", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("agents", sa.Column("typing_speed_cps", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("agents", sa.Column("style_mirror", sa.Boolean(), nullable=False, server_default="false"))
    op.add_column("agents", sa.Column("voice_replies", sa.String(10), nullable=False, server_default="off"))
    op.add_column("agents", sa.Column("voice_model", sa.String(180), nullable=False, server_default=""))
    op.add_column("agents", sa.Column("voice_name", sa.String(60), nullable=False, server_default=""))


def downgrade():
    # contract: reviewed - new in this release; the previous release ignores
    # them, so going back only loses the humanization settings.
    for column in ("voice_name", "voice_model", "voice_replies", "style_mirror", "typing_speed_cps", "split_max_parts", "split_replies"):
        op.drop_column("agents", column)
