"""Reusable declarative mixins."""
from __future__ import annotations

from datetime import datetime

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.utils.datetime import utcnow


class TimestampMixin:
    """``created_at`` / ``updated_at`` in naive UTC (see app.utils.datetime)."""

    created_at: Mapped[datetime] = mapped_column(sa.DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        sa.DateTime, nullable=False, default=utcnow, onupdate=utcnow
    )
