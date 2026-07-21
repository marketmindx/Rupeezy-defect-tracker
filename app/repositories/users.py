"""User data access."""
from __future__ import annotations

from typing import List, Optional

import sqlalchemy as sa
from flask_sqlalchemy.pagination import Pagination

from app.models import ActivityLog, Attachment, Comment, Defect, User, UserRole
from app.repositories.base import BaseRepository


class UserRepository(BaseRepository[User]):
    model = User

    def find_by_identifier(self, identifier: str) -> Optional[User]:
        """Look up by username *or* email, case-insensitively."""
        ident = (identifier or "").strip().lower()
        if not ident:
            return None
        return self.first(
            sa.or_(
                sa.func.lower(User.username) == ident,
                sa.func.lower(User.email) == ident,
            )
        )

    def identifier_taken(
        self,
        *,
        username: Optional[str] = None,
        email: Optional[str] = None,
        exclude_id: Optional[int] = None,
    ) -> bool:
        """True if the username/email is already used by another account."""
        criteria = []
        if username is not None:
            criteria.append(sa.func.lower(User.username) == username.strip().lower())
        if email is not None:
            criteria.append(sa.func.lower(User.email) == email.strip().lower())
        if not criteria:
            raise ValueError("identifier_taken() needs a username or an email")
        if exclude_id is not None:
            return self.exists(sa.or_(*criteria), User.id != exclude_id)
        return self.exists(sa.or_(*criteria))

    def has_linked_records(self, user_id: int) -> bool:
        """True if any ``ON DELETE RESTRICT`` foreign key still points at the user.

        A hard delete is only possible for accounts with no footprint. The
        blocking references mirror the schema's RESTRICT rules: defects the user
        reported, comments they authored, attachments they uploaded, and any
        activity row where they were the actor. Assigned-QA / assigned-developer
        links are ``SET NULL`` and therefore never block.
        """
        return (
            self.exists(Defect.reporter_id == user_id)
            or self.exists(Comment.author_id == user_id)
            or self.exists(Attachment.uploaded_by_id == user_id)
            or self.exists(ActivityLog.actor_id == user_id)
        )

    def count_active_admins(self, *, exclude_id: Optional[int] = None) -> int:
        criteria: "List" = [User.role == UserRole.ADMIN, User.is_active.is_(True)]
        if exclude_id is not None:
            criteria.append(User.id != exclude_id)
        return self.count(*criteria)

    def paginate_filtered(
        self,
        *,
        page: int,
        per_page: int,
        search: Optional[str] = None,
        role: Optional[UserRole] = None,
        active: Optional[bool] = None,
    ) -> Pagination:
        criteria: "List" = []
        if search:
            like = f"%{search.strip().lower()}%"
            criteria.append(
                sa.or_(
                    sa.func.lower(User.username).like(like),
                    sa.func.lower(User.full_name).like(like),
                    sa.func.lower(User.email).like(like),
                )
            )
        if role is not None:
            criteria.append(User.role == role)
        if active is not None:
            criteria.append(User.is_active.is_(active))
        return self.paginate(
            *criteria, page=page, per_page=per_page, order_by=sa.func.lower(User.username)
        )
