"""Audit trail — who changed what, when.

Rows are written by the service layer on every mutation. ``defect_id`` links
an event to a defect's timeline and cascades away with it; ``entity_type`` +
``entity_id`` survive independently, which is how a *deletion* itself stays
on record (the DELETED row is written with ``defect_id = None``).
"""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import ActivityAction, enum_column
from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.defect import Defect
    from app.models.user import User


class ActivityLog(db.Model):
    __tablename__ = "activity_log"
    __table_args__ = (sa.Index("ix_activity_log_entity", "entity_type", "entity_id"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    entity_type: Mapped[str] = mapped_column(sa.String(30), nullable=False)
    entity_id: Mapped[int] = mapped_column(sa.Integer, nullable=False)
    defect_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("defects.id", ondelete="CASCADE"), index=True
    )
    actor_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    action: Mapped[ActivityAction] = mapped_column(enum_column(ActivityAction), nullable=False)
    field: Mapped[Optional[str]] = mapped_column(sa.String(50))
    old_value: Mapped[Optional[str]] = mapped_column(sa.Text)
    new_value: Mapped[Optional[str]] = mapped_column(sa.Text)
    note: Mapped[Optional[str]] = mapped_column(sa.String(255))
    created_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=utcnow, index=True
    )

    defect: Mapped[Optional["Defect"]] = relationship(back_populates="activities")
    actor: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<ActivityLog {self.action.value} {self.entity_type}#{self.entity_id}>"
