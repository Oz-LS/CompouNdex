"""add is_filler to mixture_components

Revision ID: c68d4ebca546
Revises:
Create Date: 2026-04-14 13:03:32.626860

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'c68d4ebca546'
down_revision = None
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table('mixture_components', schema=None) as batch_op:
        batch_op.add_column(sa.Column('is_filler', sa.Boolean(), nullable=False, server_default=sa.text('0')))


def downgrade():
    with op.batch_alter_table('mixture_components', schema=None) as batch_op:
        batch_op.drop_column('is_filler')
