"""Sprint / Story / Epic data access, including the tree-view loaders.

Rollup queries use correlated subqueries (never two outer joins in one
statement — defects × stories would explode the row count).
"""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import joinedload, selectinload

from app.models import Defect, DefectStatus, Epic, Sprint, Story
from app.repositories.base import BaseRepository

_TERMINAL = [status for status in DefectStatus if status.is_terminal]


def _done_sum():
    return sa.func.coalesce(
        sa.func.sum(sa.case((Defect.status.in_(_TERMINAL), 1), else_=0)), 0
    )


class SprintRepository(BaseRepository[Sprint]):
    model = Sprint

    def number_taken(self, number: int, *, exclude_id: Optional[int] = None) -> bool:
        if exclude_id is not None:
            return self.exists(Sprint.number == number, Sprint.id != exclude_id)
        return self.exists(Sprint.number == number)

    def list_with_rollups(self) -> "List[Tuple[Sprint, int, int, int]]":
        """(sprint, defect total, defects done, story count), newest first."""
        defect_counts = (
            sa.select(
                Defect.sprint_id.label("sprint_id"),
                sa.func.count().label("total"),
                _done_sum().label("done"),
            )
            .group_by(Defect.sprint_id)
            .subquery()
        )
        story_counts = (
            sa.select(Story.sprint_id.label("sprint_id"), sa.func.count().label("stories"))
            .group_by(Story.sprint_id)
            .subquery()
        )
        rows = self.session.execute(
            sa.select(
                Sprint,
                sa.func.coalesce(defect_counts.c.total, 0),
                sa.func.coalesce(defect_counts.c.done, 0),
                sa.func.coalesce(story_counts.c.stories, 0),
            )
            .join(defect_counts, defect_counts.c.sprint_id == Sprint.id, isouter=True)
            .join(story_counts, story_counts.c.sprint_id == Sprint.id, isouter=True)
            .order_by(Sprint.number.desc())
        ).all()
        return [(sprint, int(total), int(done), int(stories))
                for sprint, total, done, stories in rows]

    def stats(self, sprint_id: int) -> "Tuple[int, int]":
        """(total defects, done defects) for one sprint."""
        row = self.session.execute(
            sa.select(sa.func.count(), _done_sum())
            .select_from(Defect)
            .where(Defect.sprint_id == sprint_id)
        ).one()
        return int(row[0]), int(row[1])

    def status_breakdown(self, sprint_id: int) -> "Dict[DefectStatus, int]":
        rows = self.session.execute(
            sa.select(Defect.status, sa.func.count())
            .where(Defect.sprint_id == sprint_id)
            .group_by(Defect.status)
        ).all()
        return {status: count for status, count in rows}

    def defects_for(self, sprint_id: int, *, limit: int = 100) -> "List[Defect]":
        """The sprint-detail defect table (capped; full list via /defects/?sprint=)."""
        return list(
            self.session.scalars(
                sa.select(Defect)
                .where(Defect.sprint_id == sprint_id)
                .options(
                    joinedload(Defect.module),
                    joinedload(Defect.assigned_developer),
                    joinedload(Defect.story),
                )
                .order_by(Defect.created_at.desc())
                .limit(limit)
            )
        )


class StoryRepository(BaseRepository[Story]):
    model = Story

    def for_sprint_with_counts(self, sprint_id: int) -> "List[Tuple[Story, int]]":
        rows = self.session.execute(
            sa.select(Story, sa.func.count(Defect.id))
            .join(Defect, Defect.story_id == Story.id, isouter=True)
            .where(Story.sprint_id == sprint_id)
            .group_by(Story.id)
            .order_by(Story.key)
        ).all()
        return [(story, int(count)) for story, count in rows]

    def tree_groups(self) -> "List[dict]":
        """Epic → stories → defects, fully eager-loaded for the tree view."""
        epics = list(
            self.session.scalars(
                sa.select(Epic)
                .options(
                    selectinload(Epic.stories).selectinload(Story.defects),
                    selectinload(Epic.stories).joinedload(Story.sprint),
                    selectinload(Epic.stories).joinedload(Story.assignee),
                    selectinload(Epic.stories).joinedload(Story.reporter),
                    selectinload(Epic.stories).selectinload(Story.labels),
                )
                .order_by(Epic.id)
            )
        )
        orphans = list(
            self.session.scalars(
                sa.select(Story)
                .where(Story.epic_id.is_(None))
                .options(
                    selectinload(Story.defects),
                    joinedload(Story.sprint),
                    joinedload(Story.assignee),
                    joinedload(Story.reporter),
                    selectinload(Story.labels),
                )
                .order_by(Story.id)
            )
        )
        groups = [
            {"epic": epic, "stories": [(story, list(story.defects)) for story in epic.stories]}
            for epic in epics
        ]
        if orphans:
            groups.append(
                {"epic": None, "stories": [(story, list(story.defects)) for story in orphans]}
            )
        return groups


class EpicRepository(BaseRepository[Epic]):
    model = Epic
