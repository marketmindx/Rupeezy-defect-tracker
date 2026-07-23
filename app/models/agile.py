"""Sprint / Epic / Story — the planning hierarchy defects hang off.

Epic ─┬─ Story ─┬─ Defect        (story tree view, Phase 6)
      │         └─ Defect
      └─ Story
Sprint ── Stories + Defects      (sprint scope, completion %)
"""
from __future__ import annotations

from datetime import date
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import Priority, SprintStatus, StoryStatus, enum_column
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.defect import Defect
    from app.models.taxonomy import Label
    from app.models.user import User

story_labels = sa.Table(
    "story_labels",
    db.metadata,
    sa.Column("story_id", sa.ForeignKey("stories.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("label_id", sa.ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
    sa.Index("ix_story_labels_label_id", "label_id"),
)


class Sprint(TimestampMixin, db.Model):
    __tablename__ = "sprints"
    __table_args__ = (sa.CheckConstraint("end_date >= start_date", name="end_after_start"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    number: Mapped[int] = mapped_column(sa.Integer, unique=True, nullable=False)
    goal: Mapped[Optional[str]] = mapped_column(sa.Text)
    start_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    end_date: Mapped[date] = mapped_column(sa.Date, nullable=False)
    status: Mapped[SprintStatus] = mapped_column(
        enum_column(SprintStatus), nullable=False, default=SprintStatus.PLANNED, index=True
    )
    #: Strapi board-sprint numeric id, when this sprint mirrors one (set by
    #: scripts/strapi_sync.py). Lets the "push to Strapi" feature target the
    #: right sprint without guessing.
    strapi_sprint_id: Mapped[Optional[int]] = mapped_column(sa.Integer)

    stories: Mapped[List["Story"]] = relationship(
        back_populates="sprint", passive_deletes="all", order_by="Story.key"
    )
    defects: Mapped[List["Defect"]] = relationship(
        back_populates="sprint", passive_deletes="all"
    )

    @property
    def is_current(self) -> bool:
        """Date-based check — independent of the status flag."""
        return self.start_date <= date.today() <= self.end_date

    @property
    def completion_pct(self) -> int:
        """% of this sprint's defects in a terminal status.

        Loads the ``defects`` collection — fine on a sprint detail page;
        dashboards and lists must use an aggregate query instead (Phase 6).
        """
        if not self.defects:
            return 0
        done = sum(1 for defect in self.defects if defect.status.is_terminal)
        return round(done * 100 / len(self.defects))

    def __repr__(self) -> str:
        return f"<Sprint {self.number} {self.name!r}>"


class Epic(TimestampMixin, db.Model):
    __tablename__ = "epics"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(sa.String(20), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(sa.String(200), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)

    stories: Mapped[List["Story"]] = relationship(
        back_populates="epic", passive_deletes="all", order_by="Story.key"
    )

    def __repr__(self) -> str:
        return f"<Epic {self.key}>"


class Story(TimestampMixin, db.Model):
    __tablename__ = "stories"

    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(sa.String(20), unique=True, nullable=False)
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)
    status: Mapped[StoryStatus] = mapped_column(
        enum_column(StoryStatus), nullable=False, default=StoryStatus.OPEN, index=True
    )
    priority: Mapped[Optional[Priority]] = mapped_column(enum_column(Priority), index=True)
    story_points: Mapped[Optional[int]] = mapped_column(sa.Integer)

    epic_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("epics.id", ondelete="SET NULL"), index=True
    )
    sprint_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("sprints.id", ondelete="SET NULL"), index=True
    )
    #: Owner and requester as recorded on the Strapi board-ticket (set by
    #: scripts/strapi_sync.py). SET NULL rather than RESTRICT — unlike a
    #: defect's reporter, a story can legitimately go unattributed.
    assignee_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    reporter_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    epic: Mapped[Optional["Epic"]] = relationship(back_populates="stories")
    sprint: Mapped[Optional["Sprint"]] = relationship(back_populates="stories")
    assignee: Mapped[Optional["User"]] = relationship(
        back_populates="assigned_stories", foreign_keys=[assignee_id]
    )
    reporter: Mapped[Optional["User"]] = relationship(
        back_populates="reported_stories", foreign_keys=[reporter_id]
    )
    defects: Mapped[List["Defect"]] = relationship(
        back_populates="story", passive_deletes="all", order_by="Defect.id"
    )
    labels: Mapped[List["Label"]] = relationship(
        secondary="story_labels", back_populates="stories", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Story {self.key}>"
