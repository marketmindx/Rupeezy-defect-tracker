"""Read-only aggregate queries for the dashboard.

Not a :class:`BaseRepository` subclass on purpose: it spans several
aggregates and returns primitives (tuples/dicts), never entities to mutate.
Every method is a single grouped query or a bounded fetch — no N+1s.
"""
from __future__ import annotations

from datetime import date, datetime
from typing import Dict, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from app.extensions import db
from app.models import (
    ActivityAction,
    ActivityLog,
    Comment,
    Defect,
    DefectStatus,
    Module,
    Severity,
    Sprint,
    SprintStatus,
    Story,
    User,
)

_TERMINAL = [status for status in DefectStatus if status.is_terminal]


class DashboardRepository:
    def __init__(self, user_id: "Optional[int]" = None) -> None:
        #: when set, every defect aggregate is scoped to defects this user
        #: reported, develops, or QAs — powering per-user dashboards. When
        #: None (e.g. admins), the dashboard spans all defects.
        self.user_id = user_id

    @property
    def session(self):
        return db.session

    def _scope(self):
        """Condition limiting defects to those the scoped user is involved in."""
        if self.user_id is None:
            return sa.true()
        uid = self.user_id
        return sa.or_(
            Defect.reporter_id == uid,
            Defect.assigned_developer_id == uid,
            Defect.assigned_qa_id == uid,
        )

    def _open_filter(self):
        return sa.and_(Defect.status.in_(DefectStatus.open_statuses()), self._scope())

    # -- counts ---------------------------------------------------------------
    def count_by_status(self) -> "Dict[DefectStatus, int]":
        rows = self.session.execute(
            sa.select(Defect.status, sa.func.count())
            .where(self._scope())
            .group_by(Defect.status)
        ).all()
        return {status: count for status, count in rows}

    def count_open_by_severity(self) -> "Dict[str, int]":
        rows = self.session.execute(
            sa.select(Defect.severity, sa.func.count())
            .where(self._open_filter())
            .group_by(Defect.severity)
        ).all()
        return {severity.value: count for severity, count in rows}

    def count_open_by_priority(self) -> "Dict[str, int]":
        rows = self.session.execute(
            sa.select(Defect.priority, sa.func.count())
            .where(self._open_filter())
            .group_by(Defect.priority)
        ).all()
        return {priority.value: count for priority, count in rows}

    # -- windowed fetches (bounded; bucketed in Python for portability) --------
    def created_since(self, start: datetime) -> "List[datetime]":
        return list(
            self.session.scalars(
                sa.select(Defect.created_at).where(Defect.created_at >= start, self._scope())
            )
        )

    def resolved_since(self, start: datetime) -> "List[datetime]":
        return list(
            self.session.scalars(
                sa.select(Defect.resolved_at).where(
                    Defect.resolved_at.is_not(None), Defect.resolved_at >= start, self._scope()
                )
            )
        )

    def open_created_dates(self) -> "List[datetime]":
        return list(
            self.session.scalars(
                sa.select(Defect.created_at).where(self._open_filter())
            )
        )

    # -- grouped rollups ---------------------------------------------------------
    def workload_rows(self) -> "List[Tuple[str, Severity, int]]":
        return [
            tuple(row)
            for row in self.session.execute(
                sa.select(User.full_name, Defect.severity, sa.func.count())
                .join(Defect, Defect.assigned_developer_id == User.id)
                .where(self._open_filter())
                .group_by(User.id, User.full_name, Defect.severity)
            ).all()
        ]

    def open_by_module(self, limit: int = 8) -> "List[Tuple[str, int]]":
        count = sa.func.count()
        return [
            tuple(row)
            for row in self.session.execute(
                sa.select(Module.name, count)
                .join(Defect, Defect.module_id == Module.id)
                .where(self._open_filter())
                .group_by(Module.id, Module.name)
                .order_by(count.desc())
                .limit(limit)
            ).all()
        ]

    def sprint_rollup(self, limit: int = 6) -> "List[Tuple[str, int, int, int]]":
        """(name, number, total defects, done defects) for the latest sprints."""
        done = sa.func.coalesce(
            sa.func.sum(sa.case((Defect.status.in_(_TERMINAL), 1), else_=0)), 0
        )
        return [
            (name, number, int(total), int(done_count))
            for name, number, total, done_count in self.session.execute(
                sa.select(Sprint.name, Sprint.number, sa.func.count(Defect.id), done)
                .join(Defect, Defect.sprint_id == Sprint.id, isouter=True)
                .where(self._scope())
                .group_by(Sprint.id, Sprint.name, Sprint.number)
                .order_by(Sprint.number.desc())
                .limit(limit)
            ).all()
        ]

    # -- today ----------------------------------------------------------------
    def counts_today(self, start: datetime) -> "Dict[str, int]":
        def count(stmt) -> int:
            return self.session.scalar(stmt) or 0

        actor_scope = sa.true() if self.user_id is None else (ActivityLog.actor_id == self.user_id)
        author_scope = sa.true() if self.user_id is None else (Comment.author_id == self.user_id)
        return {
            "reported": count(
                sa.select(sa.func.count()).select_from(Defect)
                .where(Defect.created_at >= start, self._scope())
            ),
            "resolved": count(
                sa.select(sa.func.count())
                .select_from(Defect)
                .where(Defect.resolved_at.is_not(None), Defect.resolved_at >= start, self._scope())
            ),
            "status_changes": count(
                sa.select(sa.func.count())
                .select_from(ActivityLog)
                .where(
                    ActivityLog.action == ActivityAction.STATUS_CHANGED,
                    ActivityLog.created_at >= start,
                    actor_scope,
                )
            ),
            "comments": count(
                sa.select(sa.func.count()).select_from(Comment)
                .where(Comment.created_at >= start, author_scope)
            ),
        }

    # -- feed & sprint ------------------------------------------------------------
    def recent_activity(self, limit: int = 10) -> "List[ActivityLog]":
        stmt = (
            sa.select(ActivityLog)
            .options(joinedload(ActivityLog.actor), joinedload(ActivityLog.defect))
            .order_by(ActivityLog.created_at.desc(), ActivityLog.id.desc())
        )
        if self.user_id is not None:  # my actions, or activity on defects I'm on
            stmt = stmt.outerjoin(Defect, ActivityLog.defect_id == Defect.id).where(
                sa.or_(ActivityLog.actor_id == self.user_id, self._scope())
            )
        return list(self.session.scalars(stmt.limit(limit)))

    def current_sprint(self) -> "Optional[Sprint]":
        """Sprint whose date range contains today; prefer status=Active."""
        today = date.today()
        matches = list(
            self.session.scalars(
                sa.select(Sprint)
                .where(Sprint.start_date <= today, Sprint.end_date >= today)
                .order_by(Sprint.number.desc())
            )
        )
        for sprint in matches:
            if sprint.status is SprintStatus.ACTIVE:
                return sprint
        return matches[0] if matches else None

    def sprint_stats(self, sprint_id: int) -> "Tuple[int, int]":
        """(total defects, done defects) for one sprint — one query."""
        done = sa.func.coalesce(
            sa.func.sum(sa.case((Defect.status.in_(_TERMINAL), 1), else_=0)), 0
        )
        row = self.session.execute(
            sa.select(sa.func.count(), done).select_from(Defect)
            .where(Defect.sprint_id == sprint_id, self._scope())
        ).one()
        return int(row[0]), int(row[1])

    def sprint_story_count(self, sprint_id: int) -> int:
        return (
            self.session.scalar(
                sa.select(sa.func.count()).select_from(Story).where(Story.sprint_id == sprint_id)
            )
            or 0
        )
