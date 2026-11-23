"""add_campaign_scheduled_at

Revision ID: 9a56187a6ab4
Revises: 1ed4eed96700
Create Date: 2026-11-21 14:41:29.476780

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9a56187a6ab4'
down_revision: Union[str, Sequence[str], None] = '1ed4eed96700'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.add_column(sa.Column('scheduled_at', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('campaigns', schema=None) as batch_op:
        batch_op.drop_column('scheduled_at')
