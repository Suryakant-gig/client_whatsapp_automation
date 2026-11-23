"""add_phase2_interested_replies

Revision ID: 9b8da6226850
Revises: acca08182f94
Create Date: 2026-11-21 18:10:53.893596

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '9b8da6226850'
down_revision: Union[str, Sequence[str], None] = 'acca08182f94'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    with op.batch_alter_table('leads', schema=None, recreate='always') as batch_op:
        batch_op.add_column(sa.Column('last_reply_text', sa.Text(), nullable=True))
        batch_op.add_column(sa.Column('last_replied_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('needs_manual_followup', sa.Boolean(), nullable=False, server_default=sa.text('0')))
        batch_op.add_column(sa.Column('followed_up_at', sa.DateTime(timezone=True), nullable=True))
        batch_op.add_column(sa.Column('followup_notes', sa.Text(), nullable=True))
        batch_op.create_index('ix_leads_needs_manual_followup', ['needs_manual_followup'], unique=False)
        batch_op.create_index('ix_leads_last_replied_at', ['last_replied_at'], unique=False)
        batch_op.drop_constraint('ck_leads_status_allowed', type_='check')
        batch_op.create_check_constraint(
            'ck_leads_status_allowed',
            "status IN ('Pending', 'Replied', 'Not Interested', 'Interested')",
        )


def downgrade() -> None:
    """Downgrade schema."""
    with op.batch_alter_table('leads', schema=None, recreate='always') as batch_op:
        batch_op.drop_constraint('ck_leads_status_allowed', type_='check')
        batch_op.create_check_constraint(
            'ck_leads_status_allowed',
            "status IN ('Pending', 'Replied', 'Not Interested')",
        )
        batch_op.drop_index('ix_leads_last_replied_at')
        batch_op.drop_index('ix_leads_needs_manual_followup')
        batch_op.drop_column('followup_notes')
        batch_op.drop_column('followed_up_at')
        batch_op.drop_column('needs_manual_followup')
        batch_op.drop_column('last_replied_at')
        batch_op.drop_column('last_reply_text')
