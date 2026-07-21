"""The Defect aggregate — the heart of the tracker.

Foreign-key delete rules (enforced by the database — SQLite runs with
``foreign_keys=ON``):

* module   → RESTRICT   a module with defects cannot be deleted
* reporter → RESTRICT   history must keep its author
* feature / story / sprint / assignees / duplicate_of → SET NULL
* comments / attachments / activity / label & tag links → CASCADE
"""
from __future__ import annotations

from datetime import date, datetime
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import (
    Criticality,
    DefectStatus,
    Environment,
    Platform,
    Priority,
    RegressionStatus,
    ResolutionType,
    Severity,
    enum_column,
)
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.activity import ActivityLog
    from app.models.agile import Sprint, Story
    from app.models.collaboration import Attachment, Comment
    from app.models.taxonomy import Feature, Label, Module, Tag
    from app.models.user import User


defect_labels = sa.Table(
    "defect_labels",
    db.metadata,
    sa.Column("defect_id", sa.ForeignKey("defects.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("label_id", sa.ForeignKey("labels.id", ondelete="CASCADE"), primary_key=True),
    sa.Index("ix_defect_labels_label_id", "label_id"),
)

defect_tags = sa.Table(
    "defect_tags",
    db.metadata,
    sa.Column("defect_id", sa.ForeignKey("defects.id", ondelete="CASCADE"), primary_key=True),
    sa.Column("tag_id", sa.ForeignKey("tags.id", ondelete="CASCADE"), primary_key=True),
    sa.Index("ix_defect_tags_tag_id", "tag_id"),
)


class Defect(TimestampMixin, db.Model):
    __tablename__ = "defects"
    __table_args__ = (sa.Index("ix_defects_created_at", "created_at"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    #: Human-readable business key (BUG-001) — see app.services.keys.
    defect_key: Mapped[str] = mapped_column(sa.String(20), unique=True, nullable=False)

    # -- narrative ----------------------------------------------------------
    title: Mapped[str] = mapped_column(sa.String(300), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)
    expected_result: Mapped[Optional[str]] = mapped_column(sa.Text)
    actual_result: Mapped[Optional[str]] = mapped_column(sa.Text)
    steps_to_reproduce: Mapped[Optional[str]] = mapped_column(sa.Text)

    # -- where it happened --------------------------------------------------
    platform: Mapped[Platform] = mapped_column(enum_column(Platform), nullable=False, index=True)
    environment: Mapped[Environment] = mapped_column(
        enum_column(Environment), nullable=False, default=Environment.QA, index=True
    )
    app_version: Mapped[Optional[str]] = mapped_column(sa.String(50))
    build_number: Mapped[Optional[str]] = mapped_column(sa.String(50))
    os_version: Mapped[Optional[str]] = mapped_column(sa.String(50))
    device_name: Mapped[Optional[str]] = mapped_column(sa.String(100))

    # -- classification -----------------------------------------------------
    severity: Mapped[Severity] = mapped_column(enum_column(Severity), nullable=False, index=True)
    priority: Mapped[Priority] = mapped_column(enum_column(Priority), nullable=False, index=True)
    criticality: Mapped[Optional[Criticality]] = mapped_column(enum_column(Criticality))
    status: Mapped[DefectStatus] = mapped_column(
        enum_column(DefectStatus), nullable=False, default=DefectStatus.OPEN, index=True
    )

    # -- placement ----------------------------------------------------------
    module_id: Mapped[int] = mapped_column(
        sa.ForeignKey("modules.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    feature_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("features.id", ondelete="SET NULL"), index=True
    )
    story_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("stories.id", ondelete="SET NULL"), index=True
    )
    sprint_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("sprints.id", ondelete="SET NULL"), index=True
    )

    # -- people ---------------------------------------------------------------
    reporter_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    assigned_qa_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )
    assigned_developer_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("users.id", ondelete="SET NULL"), index=True
    )

    # -- lifecycle ------------------------------------------------------------
    eta: Mapped[Optional[date]] = mapped_column(sa.Date)
    resolved_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime)
    resolution_type: Mapped[Optional[ResolutionType]] = mapped_column(enum_column(ResolutionType))
    root_cause: Mapped[Optional[str]] = mapped_column(sa.Text)
    regression_required: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)
    regression_status: Mapped[Optional[RegressionStatus]] = mapped_column(
        enum_column(RegressionStatus)
    )
    duplicate_of_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("defects.id", ondelete="SET NULL")
    )

    # -- relationships ----------------------------------------------------------
    module: Mapped["Module"] = relationship(back_populates="defects")
    feature: Mapped[Optional["Feature"]] = relationship(back_populates="defects")
    story: Mapped[Optional["Story"]] = relationship(back_populates="defects")
    sprint: Mapped[Optional["Sprint"]] = relationship(back_populates="defects")

    reporter: Mapped["User"] = relationship(
        back_populates="reported_defects", foreign_keys=[reporter_id]
    )
    assigned_qa: Mapped[Optional["User"]] = relationship(
        back_populates="qa_defects", foreign_keys=[assigned_qa_id]
    )
    assigned_developer: Mapped[Optional["User"]] = relationship(
        back_populates="developer_defects", foreign_keys=[assigned_developer_id]
    )

    duplicate_of: Mapped[Optional["Defect"]] = relationship(
        remote_side=[id], back_populates="duplicates"
    )
    duplicates: Mapped[List["Defect"]] = relationship(back_populates="duplicate_of")

    comments: Mapped[List["Comment"]] = relationship(
        back_populates="defect",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Comment.created_at",
    )
    attachments: Mapped[List["Attachment"]] = relationship(
        back_populates="defect",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Attachment.created_at",
    )
    activities: Mapped[List["ActivityLog"]] = relationship(
        back_populates="defect",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="ActivityLog.created_at",
    )
    labels: Mapped[List["Label"]] = relationship(
        secondary="defect_labels", back_populates="defects", passive_deletes=True
    )
    tags: Mapped[List["Tag"]] = relationship(
        secondary="defect_tags", back_populates="defects", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Defect {self.defect_key} [{self.status.value}] {self.title[:40]!r}>"
