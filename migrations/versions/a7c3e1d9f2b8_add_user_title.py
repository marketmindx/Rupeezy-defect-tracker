"""Add users.title — optional designation label (e.g. "VP Tech"), separate
from role.

Revision ID: a7c3e1d9f2b8
Revises: 55ff637163df
Create Date: 2026-07-22 12:17:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'a7c3e1d9f2b8'
down_revision = '55ff637163df'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('title', sa.String(length=50), nullable=True))


def downgrade():
    op.drop_column('users', 'title')
