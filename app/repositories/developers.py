"""Per-person defect aggregates for the developer directory and profiles.

Read-only rollups over ``Defect`` grouped by the people columns
(``assigned_developer_id`` / ``assigned_qa_id`` / ``reporter_id``).
Averages are computed in Python from (created_at, resolved_at) pairs so the
arithmetic is identical on SQLite and PostgreSQL.
"""
from __future__ import annotations

from datetime import date
from typing import Dict, List, Optional, Tuple

import sqlalchemy as sa
from sqlalchemy.orm import joinedload

from app.models import Defect, DefectStatus, Severity, User
from app.repositories.base import BaseRepository

_TERMINAL = [status for status in DefectStatus if status.is_terminal]


def _sum_case(condition) -> "sa.ColumnElement[int]":
    return sa.func.coalesce(sa.func.sum(sa.case((condition, 1), else_=0)), 0)


class DeveloperRepository(BaseRepository[User]):
    model = User

    # -- directory -----------------------------------------------------------
    def counts_by(self, fk_column) -> "Dict[int, Dict[str, int]]":
        """{user_id: {total, done, critical_open}} grouped by a people column."""
        rows = self.session.execute(
            sa.select(
                fk_column,
                sa.func.count(),
                _sum_case(Defect.status.in_(_TERMINAL)),
                _sum_case(
                    sa.and_(
                        Defect.severity == Severity.CRITICAL,
                        Defect.status.not_in(_TERMINAL),
                    )
                ),
            )
            .where(fk_column.is_not(None))
            .group_by(fk_column)
        ).all()
        return {
            row[0]: {"total": int(row[1]), "done": int(row[2]), "critical_open": int(row[3])}
            for row in rows
        }

    def reported_counts(self) -> "Dict[int, int]":
        rows = self.session.execute(
            sa.select(Defect.reporter_id, sa.func.count()).group_by(Defect.reporter_id)
        ).all()
        return {row[0]: int(row[1]) for row in rows}

    def users_with_role(self, role) -> "List[User]":
        return list(
            self.session.scalars(
                sa.select(User)
                .where(User.role == role)
                .order_by(User.is_active.desc(), sa.func.lower(User.full_name))
            )
        )

    # -- profile stats -------------------------------------------------------
    def assignment_stats(self, user_id: int) -> "Dict[str, int]":
        row = self.session.execute(
            sa.select(
                sa.func.count(),
                _sum_case(Defect.status.in_(_TERMINAL)),
                _sum_case(
                    sa.and_(
                        Defect.severity == Severity.CRITICAL,
                        Defect.status.not_in(_TERMINAL),
                    )
                ),
                _sum_case(
                    sa.and_(
                        Defect.severity == Severity.HIGH,
                        Defect.status.not_in(_TERMINAL),
                    )
                ),
                _sum_case(
                    sa.and_(
                        Defect.status.not_in(_TERMINAL),
                        Defect.eta.is_not(None),
                        Defect.eta < date.today(),
                    )
                ),
            ).where(Defect.assigned_developer_id == user_id)
        ).one()
        total, done = int(row[0]), int(row[1])
        return {
            "assigned_total": total,
            "done": done,
            "open": total - done,
            "critical_open": int(row[2]),
            "high_open": int(row[3]),
            "overdue": int(row[4]),
        }

    def open_severity_breakdown(self, user_id: int) -> "Dict[Severity, int]":
        rows = self.session.execute(
            sa.select(Defect.severity, sa.func.count())
            .where(
                Defect.assigned_developer_id == user_id,
                Defect.status.not_in(_TERMINAL),
            )
            .group_by(Defect.severity)
        ).all()
        return {severity: int(count) for severity, count in rows}

    def status_breakdown(self, user_id: int) -> "Dict[DefectStatus, int]":
        rows = self.session.execute(
            sa.select(Defect.status, sa.func.count())
            .where(Defect.assigned_developer_id == user_id)
            .group_by(Defect.status)
        ).all()
        return {status: int(count) for status, count in rows}

    def avg_resolution_days(self, user_id: int) -> "Optional[float]":
        """Mean created→resolved time of this developer's resolved defects."""
        pairs: "List[Tuple]" = self.session.execute(
            sa.select(Defect.created_at, Defect.resolved_at).where(
                Defect.assigned_developer_id == user_id,
                Defect.resolved_at.is_not(None),
            )
        ).all()
        if not pairs:
            return None
        total_days = sum(
            (resolved - created).total_seconds() / 86400 for created, resolved in pairs
        )
        return round(total_days / len(pairs), 1)

    def qa_open_count(self, user_id: int) -> int:
        return int(
            self.session.scalar(
                sa.select(sa.func.count()).where(
                    Defect.assigned_qa_id == user_id,
                    Defect.status.not_in(_TERMINAL),
                )
            )
        )

    def reported_count(self, user_id: int) -> int:
        return int(
            self.session.scalar(
                sa.select(sa.func.count()).where(Defect.reporter_id == user_id)
            )
        )

    # -- defect lists --------------------------------------------------------
    def _defects(self, *criteria, limit: int = 50) -> "List[Defect]":
        return list(
            self.session.scalars(
                sa.select(Defect)
                .where(*criteria)
                .options(
                    joinedload(Defect.module),
                    joinedload(Defect.story),
                    joinedload(Defect.sprint),
                )
                .order_by(Defect.updated_at.desc())
                .limit(limit)
            )
        )

    def open_assigned(self, user_id: int) -> "List[Defect]":
        return self._defects(
            Defect.assigned_developer_id == user_id, Defect.status.not_in(_TERMINAL)
        )

    def all_assigned(self, user_id: int) -> "List[Defect]":
        return self._defects(Defect.assigned_developer_id == user_id)

    def qa_queue(self, user_id: int) -> "List[Defect]":
        return self._defects(
            Defect.assigned_qa_id == user_id, Defect.status.not_in(_TERMINAL)
        )

    def reported(self, user_id: int) -> "List[Defect]":
        return self._defects(Defect.reporter_id == user_id)
