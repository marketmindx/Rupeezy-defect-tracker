"""Add Story.assignee_id/reporter_id/priority and story_labels
— backs the expandable story-detail view on the story tree, sourced from
the Strapi board-ticket's assignee/reporter/priority/labels.

Revision ID: b2d8e5f0a3c4
Revises: f4b9d2a6c1e7
Create Date: 2026-07-22 15:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = 'b2d8e5f0a3c4'
down_revision = 'f4b9d2a6c1e7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'stories',
        sa.Column('priority', sa.Enum('P0', 'P1', 'P2', 'P3', name='priority', native_enum=False),
                  nullable=True),
    )
    op.add_column('stories', sa.Column('assignee_id', sa.Integer(), nullable=True))
    op.add_column('stories', sa.Column('reporter_id', sa.Integer(), nullable=True))
    with op.batch_alter_table('stories', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_stories_priority'), ['priority'], unique=False)
        batch_op.create_index(batch_op.f('ix_stories_assignee_id'), ['assignee_id'], unique=False)
        batch_op.create_index(batch_op.f('ix_stories_reporter_id'), ['reporter_id'], unique=False)
        batch_op.create_foreign_key(
            batch_op.f('fk_stories_assignee_id_users'), 'users', ['assignee_id'], ['id'],
            ondelete='SET NULL',
        )
        batch_op.create_foreign_key(
            batch_op.f('fk_stories_reporter_id_users'), 'users', ['reporter_id'], ['id'],
            ondelete='SET NULL',
        )

    op.create_table(
        'story_labels',
        sa.Column('story_id', sa.Integer(), nullable=False),
        sa.Column('label_id', sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(['story_id'], ['stories.id'],
                                 name=op.f('fk_story_labels_story_id_stories'), ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['label_id'], ['labels.id'],
                                 name=op.f('fk_story_labels_label_id_labels'), ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('story_id', 'label_id', name=op.f('pk_story_labels')),
    )
    with op.batch_alter_table('story_labels', schema=None) as batch_op:
        batch_op.create_index(batch_op.f('ix_story_labels_label_id'), ['label_id'], unique=False)


def downgrade():
    op.drop_table('story_labels')
    with op.batch_alter_table('stories', schema=None) as batch_op:
        batch_op.drop_constraint(batch_op.f('fk_stories_reporter_id_users'), type_='foreignkey')
        batch_op.drop_constraint(batch_op.f('fk_stories_assignee_id_users'), type_='foreignkey')
        batch_op.drop_index(batch_op.f('ix_stories_reporter_id'))
        batch_op.drop_index(batch_op.f('ix_stories_assignee_id'))
        batch_op.drop_index(batch_op.f('ix_stories_priority'))
        batch_op.drop_column('reporter_id')
        batch_op.drop_column('assignee_id')
        batch_op.drop_column('priority')
