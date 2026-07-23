"""Add Defect.strapi_ticket_id/strapi_synced_at and Sprint.strapi_sprint_id
— backs the "create as Bug in Strapi" feature.

Revision ID: f4b9d2a6c1e7
Revises: a7c3e1d9f2b8
Create Date: 2026-07-22 12:30:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'f4b9d2a6c1e7'
down_revision = 'a7c3e1d9f2b8'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('defects', sa.Column('strapi_ticket_id', sa.String(length=20), nullable=True))
    op.create_index(op.f('ix_defects_strapi_ticket_id'), 'defects', ['strapi_ticket_id'])
    op.add_column('defects', sa.Column('strapi_synced_at', sa.DateTime(), nullable=True))
    op.add_column('sprints', sa.Column('strapi_sprint_id', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('sprints', 'strapi_sprint_id')
    op.drop_column('defects', 'strapi_synced_at')
    op.drop_index(op.f('ix_defects_strapi_ticket_id'), table_name='defects')
    op.drop_column('defects', 'strapi_ticket_id')
