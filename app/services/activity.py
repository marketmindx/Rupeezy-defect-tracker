"""Audit-trail writing, shared by every mutating service.

Never commits — activity rows join the caller's transaction so an audit
entry can never exist for a change that rolled back (and vice versa).
"""
from __future__ import annotations

from typing import TYPE_CHECKING, Mapping, Optional, Tuple

from app.extensions import db
from app.models import ActivityAction, ActivityLog
from app.services.base import BaseService

if TYPE_CHECKING:
    from app.models import Defect, User


class ActivityService(BaseService):
    def log(
        self,
        *,
        entity_type: str,
        entity_id: int,
        actor: "User",
        action: ActivityAction,
        defect: "Optional[Defect]" = None,
        field: Optional[str] = None,
        old_value: Optional[str] = None,
        new_value: Optional[str] = None,
        note: Optional[str] = None,
    ) -> ActivityLog:
        """Stage one audit row in the current transaction."""
        entry = ActivityLog(
            entity_type=entity_type,
            entity_id=entity_id,
            defect=defect,
            actor=actor,
            action=action,
            field=field,
            old_value=old_value,
            new_value=new_value,
            note=note,
        )
        db.session.add(entry)
        return entry

    def log_field_changes(
        self,
        *,
        entity_type: str,
        entity_id: int,
        actor: "User",
        changes: "Mapping[str, Tuple[object, object]]",
        defect: "Optional[Defect]" = None,
    ) -> None:
        """One UPDATED row per changed field: {field: (old, new)}."""
        for field, (old, new) in changes.items():
            self.log(
                entity_type=entity_type,
                entity_id=entity_id,
                actor=actor,
                action=ActivityAction.UPDATED,
                defect=defect,
                field=field,
                old_value=None if old is None else str(old),
                new_value=None if new is None else str(new),
            )
