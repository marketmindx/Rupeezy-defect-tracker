"""Monotonic per-entity counters backing human-readable keys (BUG-001).

Kept separate from the entity tables so keys never depend on (or leak)
auto-increment primary keys, survive row deletion without reuse, and stay
portable across database backends. See :mod:`app.services.keys`.
"""
from __future__ import annotations

import sqlalchemy as sa
from sqlalchemy.orm import Mapped, mapped_column

from app.extensions import db


class KeyCounter(db.Model):
    __tablename__ = "key_counters"

    entity: Mapped[str] = mapped_column(sa.String(30), primary_key=True)
    value: Mapped[int] = mapped_column(sa.Integer, nullable=False, default=0)

    def __repr__(self) -> str:
        return f"<KeyCounter {self.entity}={self.value}>"
