"""add_respondents_table

Revision ID: b2c3d4e5f6a7
Revises: 9b8da6226850
Create Date: 2026-11-24 18:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'b2c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = '9b8da6226850'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema: create respondents table."""
    op.create_table(
        'respondents',
        sa.Column('id', sa.Integer(), autoincrement=True, nullable=False),
        sa.Column('lead_id', sa.Integer(), nullable=True),
        sa.Column('phone_number', sa.String(length=32), nullable=False),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('classification', sa.String(length=32), nullable=False, server_default=sa.text("'UNCLASSIFIED'")),
        sa.Column('first_reply_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('last_reply_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('original_campaign_id', sa.Integer(), nullable=True),
        sa.Column('internal_notes', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(['lead_id'], ['leads.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['original_campaign_id'], ['campaigns.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('phone_number', name='uq_respondents_phone_number'),
        sa.CheckConstraint(
            "classification IN ('UNCLASSIFIED', 'INTERESTED', 'NOT_INTERESTED', 'OTHER')",
            name='ck_respondents_classification_allowed',
        ),
    )
    op.create_index('ix_respondents_phone_number', 'respondents', ['phone_number'], unique=True)
    op.create_index('ix_respondents_classification', 'respondents', ['classification'], unique=False)
    op.create_index('ix_respondents_last_reply_at', 'respondents', ['last_reply_at'], unique=False)
    op.create_index('ix_respondents_lead_id', 'respondents', ['lead_id'], unique=False)
    op.create_index('ix_respondents_campaign_id', 'respondents', ['original_campaign_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema: drop respondents table."""
    op.drop_index('ix_respondents_campaign_id', table_name='respondents')
    op.drop_index('ix_respondents_lead_id', table_name='respondents')
    op.drop_index('ix_respondents_last_reply_at', table_name='respondents')
    op.drop_index('ix_respondents_classification', table_name='respondents')
    op.drop_index('ix_respondents_phone_number', table_name='respondents')
    op.drop_table('respondents')
