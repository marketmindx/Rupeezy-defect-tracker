"""User accounts and Flask-Login integration."""
from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, List, Optional

import sqlalchemy as sa
from flask import current_app
from flask_login import UserMixin
from sqlalchemy.orm import Mapped, mapped_column, relationship
from werkzeug.security import check_password_hash, generate_password_hash

from app.extensions import db, login_manager
from app.models.enums import UserRole, enum_column
from app.models.mixins import TimestampMixin

if TYPE_CHECKING:
    from app.models.defect import Defect


class User(TimestampMixin, UserMixin, db.Model):
    """An account: Admin, QA or Developer.

    Users are deactivated (``is_active = False``), never hard-deleted —
    defect history must keep pointing at real people. The database backs
    this up: ``reporter_id`` is ON DELETE RESTRICT.
    """

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(sa.String(50), unique=True, nullable=False)
    email: Mapped[str] = mapped_column(sa.String(255), unique=True, nullable=False)
    full_name: Mapped[str] = mapped_column(sa.String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(sa.String(255), nullable=False)
    role: Mapped[UserRole] = mapped_column(enum_column(UserRole), nullable=False, index=True)
    is_active: Mapped[bool] = mapped_column(sa.Boolean, nullable=False, default=True)
    last_login_at: Mapped[Optional[datetime]] = mapped_column(sa.DateTime)

    # passive_deletes="all": let the database apply its own FK rules
    # (RESTRICT / SET NULL) instead of SQLAlchemy pre-emptively nulling
    # child foreign keys.
    reported_defects: Mapped[List["Defect"]] = relationship(
        back_populates="reporter",
        foreign_keys="Defect.reporter_id",
        passive_deletes="all",
    )
    qa_defects: Mapped[List["Defect"]] = relationship(
        back_populates="assigned_qa",
        foreign_keys="Defect.assigned_qa_id",
        passive_deletes="all",
    )
    developer_defects: Mapped[List["Defect"]] = relationship(
        back_populates="assigned_developer",
        foreign_keys="Defect.assigned_developer_id",
        passive_deletes="all",
    )

    # -- auth helpers -------------------------------------------------------
    def set_password(self, password: str) -> None:
        # Method comes from config: Werkzeug's scrypt default doesn't exist
        # on LibreSSL Python builds (macOS system Python) — see settings.py.
        self.password_hash = generate_password_hash(
            password, method=current_app.config["PASSWORD_HASH_METHOD"]
        )

    def check_password(self, password: str) -> bool:
        return check_password_hash(self.password_hash, password)

    # -- role helpers -------------------------------------------------------
    @property
    def is_admin(self) -> bool:
        return self.role is UserRole.ADMIN

    @property
    def is_qa(self) -> bool:
        return self.role is UserRole.QA

    @property
    def is_developer(self) -> bool:
        return self.role is UserRole.DEVELOPER

    def __repr__(self) -> str:
        return f"<User {self.username} ({self.role.value})>"


@login_manager.user_loader
def load_user(user_id: str) -> Optional[User]:
    """Session cookie → User lookup (replaces the Phase 1 placeholder)."""
    try:
        return db.session.get(User, int(user_id))
    except (TypeError, ValueError):
        return None
