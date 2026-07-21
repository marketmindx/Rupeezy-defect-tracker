"""Comments (threaded) and attachments on defects."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.extensions import db
from app.models.enums import AttachmentKind, enum_column
from app.models.mixins import TimestampMixin
from app.utils.datetime import utcnow

if TYPE_CHECKING:
    from app.models.defect import Defect
    from app.models.user import User


class Comment(TimestampMixin, db.Model):
    """A comment on a defect; ``parent_id`` makes threads (one level or many)."""

    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True)
    defect_id: Mapped[int] = mapped_column(
        sa.ForeignKey("defects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    author_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    parent_id: Mapped[Optional[int]] = mapped_column(
        sa.ForeignKey("comments.id", ondelete="CASCADE"), index=True
    )
    body: Mapped[str] = mapped_column(sa.Text, nullable=False)
    is_edited: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=False)

    defect: Mapped["Defect"] = relationship(back_populates="comments")
    author: Mapped["User"] = relationship()
    parent: Mapped[Optional["Comment"]] = relationship(
        remote_side=[id], back_populates="replies"
    )
    replies: Mapped[List["Comment"]] = relationship(
        back_populates="parent",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="Comment.created_at",
    )

    def __repr__(self) -> str:
        return f"<Comment #{self.id} on defect {self.defect_id}>"


class Attachment(db.Model):
    """A file attached to a defect (screenshot / video / log).

    Files live in UPLOAD_FOLDER under ``stored_filename`` (random name — the
    user-supplied name is display-only and never touches the filesystem).
    Immutable once created, so no ``updated_at``.
    """

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    defect_id: Mapped[int] = mapped_column(
        sa.ForeignKey("defects.id", ondelete="CASCADE"), nullable=False, index=True
    )
    uploaded_by_id: Mapped[int] = mapped_column(
        sa.ForeignKey("users.id", ondelete="RESTRICT"), nullable=False
    )
    kind: Mapped[AttachmentKind] = mapped_column(
        enum_column(AttachmentKind), nullable=False, default=AttachmentKind.OTHER
    )
    original_filename: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    stored_filename: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    content_type: Mapped[Optional[str]] = mapped_column(sa.String(100))
    size_bytes: Mapped[int] = mapped_column(sa.BigInteger, nullable=False, default=0)
    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)

    defect: Mapped["Defect"] = relationship(back_populates="attachments")
    uploaded_by: Mapped["User"] = relationship()

    def __repr__(self) -> str:
        return f"<Attachment {self.original_filename} ({self.kind.value})>"
