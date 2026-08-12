"""add_sop_fields_to_workorder_type_kb

Revision ID: b001_sop
Revises: a001_add_data_pool_backfill
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = 'b001_sop'
down_revision: Union[str, None] = 'a001_add_data_pool_backfill'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('workorder_type_kb', sa.Column('guidance_ref', sa.String(length=128), nullable=True))
    op.add_column('workorder_type_kb', sa.Column('sop_purpose', sa.Text(), nullable=True))
    op.add_column('workorder_type_kb', sa.Column('sop_scope', sa.Text(), nullable=True))
    op.add_column('workorder_type_kb', sa.Column('sop_steps', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('workorder_type_kb', sa.Column('sop_acceptance', sa.Text(), nullable=True))
    op.add_column('workorder_type_kb', sa.Column('sop_backfill_required', sa.Boolean(), server_default='true', nullable=False))
    op.add_column('workorder_type_kb', sa.Column('sop_escalation', postgresql.JSONB(astext_type=sa.Text()), nullable=True))
    op.add_column('workorder_type_kb', sa.Column('sop_related_guidance', postgresql.JSONB(astext_type=sa.Text()), nullable=True))


def downgrade() -> None:
    op.drop_column('workorder_type_kb', 'sop_related_guidance')
    op.drop_column('workorder_type_kb', 'sop_escalation')
    op.drop_column('workorder_type_kb', 'sop_backfill_required')
    op.drop_column('workorder_type_kb', 'sop_acceptance')
    op.drop_column('workorder_type_kb', 'sop_steps')
    op.drop_column('workorder_type_kb', 'sop_scope')
    op.drop_column('workorder_type_kb', 'sop_purpose')
    op.drop_column('workorder_type_kb', 'guidance_ref')