"""Defect data access: keyed lookups and filtered, sorted, paginated lists."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import List, Optional

import sqlalchemy as sa
from flask_sqlalchemy.pagination import Pagination
from sqlalchemy.orm import joinedload, selectinload

from app.extensions import db
from app.models import (
    ActivityLog,
    Attachment,
    Comment,
    Defect,
    DefectStatus,
    Platform,
    Priority,
    RegressionStatus,
    Severity,
)
from app.repositories.base import BaseRepository

#: Severity is stored as text ("Critical" < "High" < "Low" < "Medium"
#: alphabetically), so ordering needs an explicit rank.
_SEVERITY_RANK = sa.case(
    (Defect.severity == Severity.CRITICAL, 0),
    (Defect.severity == Severity.HIGH, 1),
    (Defect.severity == Severity.MEDIUM, 2),
    else_=3,
)

#: Sort keys exposed to the UI. P0..P3 sort correctly as plain text.
_SORTS = {
    "created": Defect.created_at,
    "updated": Defect.updated_at,
    "key": Defect.id,
    "severity": _SEVERITY_RANK,
    "priority": Defect.priority,
}


@dataclass
class DefectFilters:
    """Parsed list-view filters — the contract the dashboard chips target."""

    q: Optional[str] = None
    status: Optional[DefectStatus] = None
    state: Optional[str] = None              # "open" (non-terminal) | "done"
    severity: Optional[Severity] = None
    priority: Optional[Priority] = None
    platform: Optional[Platform] = None
    module_id: Optional[int] = None
    sprint_id: Optional[int] = None
    story_id: Optional[int] = None
    developer_id: Optional[int] = None
    qa_id: Optional[int] = None
    reporter_id: Optional[int] = None
    assignee: Optional[str] = None           # "unassigned"
    regression: Optional[RegressionStatus] = None
    created_from: Optional[datetime] = None  # inclusive
    created_to: Optional[datetime] = None    # exclusive
    sort: str = "created"
    direction: str = "desc"


class DefectRepository(BaseRepository[Defect]):
    model = Defect

    def get_by_key(self, defect_key: str) -> Optional[Defect]:
        key = (defect_key or "").strip().upper()
        if not key:
            return None
        return self.first(sa.func.upper(Defect.defect_key) == key)

    def get_detail(self, defect_key: str) -> Optional[Defect]:
        """Detail-page fetch with every relationship eager-loaded."""
        key = (defect_key or "").strip().upper()
        stmt = (
            sa.select(Defect)
            .where(sa.func.upper(Defect.defect_key) == key)
            .options(
                joinedload(Defect.module),
                joinedload(Defect.feature),
                joinedload(Defect.story),
                joinedload(Defect.sprint),
                joinedload(Defect.reporter),
                joinedload(Defect.assigned_qa),
                joinedload(Defect.assigned_developer),
                joinedload(Defect.duplicate_of),
                selectinload(Defect.duplicates),
                selectinload(Defect.labels),
                selectinload(Defect.tags),
                selectinload(Defect.attachments).joinedload(Attachment.uploaded_by),
                selectinload(Defect.comments).joinedload(Comment.author),
                selectinload(Defect.activities).joinedload(ActivityLog.actor),
            )
        )
        return self.session.scalars(stmt).one_or_none()

    def list_filtered(
        self, filters: DefectFilters, *, limit: Optional[int] = 5000
    ) -> "List[Defect]":
        """Full filtered result for exports (capped, eager-loaded, unpaginated)."""
        stmt = sa.select(Defect).options(
            joinedload(Defect.module),
            joinedload(Defect.feature),
            joinedload(Defect.story),
            joinedload(Defect.sprint),
            joinedload(Defect.reporter),
            joinedload(Defect.assigned_qa),
            joinedload(Defect.assigned_developer),
            joinedload(Defect.duplicate_of),
            selectinload(Defect.labels),
            selectinload(Defect.tags),
        )
        criteria = self._criteria(filters)
        if criteria:
            stmt = stmt.where(*criteria)
        stmt = stmt.order_by(*self._order(filters))
        if limit:
            stmt = stmt.limit(limit)
        return list(self.session.scalars(stmt).unique())

    def paginate_filtered(
        self, filters: DefectFilters, *, page: int, per_page: int
    ) -> Pagination:
        stmt = sa.select(Defect).options(
            joinedload(Defect.module),
            joinedload(Defect.assigned_developer),
            joinedload(Defect.sprint),
            joinedload(Defect.story),
        )
        criteria = self._criteria(filters)
        if criteria:
            stmt = stmt.where(*criteria)
        stmt = stmt.order_by(*self._order(filters))
        return db.paginate(stmt, page=page, per_page=per_page, error_out=False)

    # -- internals ------------------------------------------------------------
    @staticmethod
    def _criteria(f: DefectFilters) -> List:
        criteria: List = []
        if f.q:
            like = f"%{f.q.strip().lower()}%"
            criteria.append(
                sa.or_(
                    sa.func.lower(Defect.defect_key).like(like),
                    sa.func.lower(Defect.title).like(like),
                )
            )
        if f.status is not None:
            criteria.append(Defect.status == f.status)
        elif f.state == "open":
            criteria.append(Defect.status.in_(DefectStatus.open_statuses()))
        elif f.state == "done":
            criteria.append(
                Defect.status.in_([s for s in DefectStatus if s.is_terminal])
            )
        if f.severity is not None:
            criteria.append(Defect.severity == f.severity)
        if f.priority is not None:
            criteria.append(Defect.priority == f.priority)
        if f.platform is not None:
            criteria.append(Defect.platform == f.platform)
        if f.module_id:
            criteria.append(Defect.module_id == f.module_id)
        if f.sprint_id:
            criteria.append(Defect.sprint_id == f.sprint_id)
        if f.story_id:
            criteria.append(Defect.story_id == f.story_id)
        if f.developer_id:
            criteria.append(Defect.assigned_developer_id == f.developer_id)
        if f.qa_id:
            criteria.append(Defect.assigned_qa_id == f.qa_id)
        if f.reporter_id:
            criteria.append(Defect.reporter_id == f.reporter_id)
        if f.assignee == "unassigned":
            criteria.append(Defect.assigned_developer_id.is_(None))
        if f.regression is not None:
            criteria.append(Defect.regression_status == f.regression)
        if f.created_from is not None:
            criteria.append(Defect.created_at >= f.created_from)
        if f.created_to is not None:
            criteria.append(Defect.created_at < f.created_to)
        return criteria

    @staticmethod
    def _order(f: DefectFilters) -> List:
        expr = _SORTS.get(f.sort, Defect.created_at)
        primary = expr.asc() if f.direction == "asc" else expr.desc()
        return [primary, Defect.id.desc()]
