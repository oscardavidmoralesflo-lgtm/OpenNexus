"""Rename the voice-notes voice column so phone agents can use ``voice_name``.

``agents.voice_name`` (from 0063) holds the TTS voice for humanized voice
notes. The phone agents brought in by the next revision store the ElevenLabs
voice's display name under that same name, so this one moves the voice-notes
value to ``voice_note_voice``. The data is kept."""
from alembic import op

revision = "0066_voice_note_voice"
down_revision = "0065_agent_media_assets"
branch_labels = None
depends_on = None


def upgrade():
    op.alter_column("agents", "voice_name", new_column_name="voice_note_voice")


def downgrade():
    op.alter_column("agents", "voice_note_voice", new_column_name="voice_name")
