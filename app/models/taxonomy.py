"""Product taxonomy (modules / features) and cross-cutting labels & tags.

Modules and features are curated structure (where a bug lives); labels and
tags are free vocabulary (how a bug is characterised). Both label and tag
sets exist because the QA spec tracks them separately: labels are coloured,
curated chips, tags are lightweight free-text markers.
"""
from __future__ import annotations

from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.agile import Story
    from app.models.defect import Defect


class Module(TimestampMixin, db.Model):
    """Top-level product area (e.g. Payments, Onboarding & KYC)."""

    __tablename__ = "modules"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(100), unique=True, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)

    features: Mapped[List["Feature"]] = relationship(
        back_populates="module",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Feature.name",
    )
    # No cascade: defects.module_id is ON DELETE RESTRICT — a module that
    # still has defects cannot be deleted (retire it with is_active=False).
    defects: Mapped[List["Defect"]] = relationship(
        back_populates="module", passive_deletes="all"
    )

    def __repr__(self) -> str:
        return f"<Module {self.name}>"


class Feature(TimestampMixin, db.Model):
    """A feature within a module (e.g. Payments → UPI collect)."""

    __tablename__ = "features"
    __table_args__ = (sa.UniqueConstraint("module_id", "name"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    module_id: Mapped[int] = mapped_column(
        sa.ForeignKey("modules.id", ondelete="CASCADE"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(sa.String(100), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(sa.Text)

    module: Mapped["Module"] = relationship(back_populates="features")
    defects: Mapped[List["Defect"]] = relationship(
        back_populates="feature", passive_deletes="all"
    )

    def __repr__(self) -> str:
        return f"<Feature {self.name}>"


class Label(db.Model):
    """Curated, coloured chip (e.g. regression, payment-critical)."""

    __tablename__ = "labels"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(50), unique=True, nullable=False)
    color: Mapped[str] = mapped_column(sa.String(7), nullable=False, default="#6c757d")

    defects: Mapped[List["Defect"]] = relationship(
        secondary="defect_labels", back_populates="labels", passive_deletes=True
    )
    stories: Mapped[List["Story"]] = relationship(
        secondary="story_labels", back_populates="labels", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Label {self.name}>"


class Tag(db.Model):
    """Free-text marker (e.g. upi, android14)."""

    __tablename__ = "tags"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(sa.String(50), unique=True, nullable=False)

    defects: Mapped[List["Defect"]] = relationship(
        secondary="defect_tags", back_populates="tags", passive_deletes=True
    )

    def __repr__(self) -> str:
        return f"<Tag {self.name}>"
