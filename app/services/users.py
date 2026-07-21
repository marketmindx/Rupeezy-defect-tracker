"""User management: creation, profile updates, activation, password resets.

Every mutation is audit-logged and guarded by two invariants:
* you cannot deactivate yourself or remove your own admin role, and
* the system never ends up without an active admin.
"""
from __future__ import annotations

from typing import Optional

from flask_sqlalchemy.pagination import Pagination

from app.exceptions import BusinessRuleError, ConflictError, ValidationError
from app.models import ActivityAction, User, UserRole
from app.repositories.users import UserRepository
from app.services.activity import ActivityService
from app.services.base import BaseService

MIN_PASSWORD_LENGTH = 8


class UserService(BaseService):
    def __init__(
        self,
        repository: Optional[UserRepository] = None,
        activity: Optional[ActivityService] = None,
    ) -> None:
        self.repository = repository or UserRepository()
        self.activity = activity or ActivityService()

    # -- queries -------------------------------------------------------------
    def get_user(self, user_id: int) -> User:
        return self.repository.get_or_raise(user_id)

    def paginate_users(
        self,
        *,
        page: int,
        per_page: int,
        search: Optional[str] = None,
        role: Optional[UserRole] = None,
        active: Optional[bool] = None,
    ) -> Pagination:
        return self.repository.paginate_filtered(
            page=page, per_page=per_page, search=search, role=role, active=active
        )

    # -- mutations -----------------------------------------------------------
    def create_user(
        self,
        *,
        actor: User,
        username: str,
        email: str,
        full_name: str,
        role: UserRole,
        password: str,
        is_active: bool = True,
    ) -> User:
        username = username.strip()
        email = email.strip().lower()
        self._validate_password(password)
        if self.repository.identifier_taken(username=username):
            raise ConflictError(f"Username '{username}' is already taken.")
        if self.repository.identifier_taken(email=email):
            raise ConflictError(f"Email '{email}' is already in use.")

        user = User(
            username=username,
            email=email,
            full_name=full_name.strip(),
            role=role,
            is_active=is_active,
        )
        user.set_password(password)
        self.repository.add(user)
        self.repository.flush()
        self.activity.log(
            entity_type="user",
            entity_id=user.id,
            actor=actor,
            action=ActivityAction.CREATED,
            new_value=user.username,
        )
        self.commit()
        return user

    def update_profile(
        self,
        *,
        actor: User,
        user_id: int,
        username: str,
        email: str,
        full_name: str,
        role: UserRole,
        is_active: bool,
    ) -> User:
        user = self.repository.get_or_raise(user_id)
        username = username.strip()
        email = email.strip().lower()
        full_name = full_name.strip()
        self._guard_admin_invariants(actor=actor, target=user, new_role=role, new_active=is_active)

        changes: "dict[str, tuple[object, object]]" = {}
        if username != user.username:
            if self.repository.identifier_taken(username=username, exclude_id=user.id):
                raise ConflictError(f"Username '{username}' is already taken.")
            changes["username"] = (user.username, username)
            user.username = username
        if email != user.email:
            if self.repository.identifier_taken(email=email, exclude_id=user.id):
                raise ConflictError(f"Email '{email}' is already in use.")
            changes["email"] = (user.email, email)
            user.email = email
        if full_name != user.full_name:
            changes["full_name"] = (user.full_name, full_name)
            user.full_name = full_name
        if role is not user.role:
            changes["role"] = (user.role.value, role.value)
            user.role = role
        if is_active != user.is_active:
            changes["is_active"] = (
                "Active" if user.is_active else "Inactive",
                "Active" if is_active else "Inactive",
            )
            user.is_active = is_active

        if changes:
            self.activity.log_field_changes(
                entity_type="user", entity_id=user.id, actor=actor, changes=changes
            )
            self.commit()
        return user

    def toggle_active(self, *, actor: User, user_id: int) -> User:
        user = self.repository.get_or_raise(user_id)
        new_active = not user.is_active
        if not new_active:
            self._guard_admin_invariants(
                actor=actor, target=user, new_role=user.role, new_active=False
            )
        old = "Active" if user.is_active else "Inactive"
        user.is_active = new_active
        self.activity.log(
            entity_type="user",
            entity_id=user.id,
            actor=actor,
            action=ActivityAction.UPDATED,
            field="is_active",
            old_value=old,
            new_value="Active" if new_active else "Inactive",
        )
        self.commit()
        return user

    def delete_user(self, *, actor: User, user_id: int) -> str:
        """Permanently remove an account, returning the deleted username.

        Only accounts with no footprint can be hard-deleted; the schema's
        ``RESTRICT`` foreign keys are enforced here as a friendly conflict
        rather than a raw database error. Callers should offer *deactivate*
        (``toggle_active``) for users that carry defect or activity history.
        """
        user = self.repository.get_or_raise(user_id)
        if user.id == actor.id:
            raise BusinessRuleError("You cannot delete your own account.")
        if (
            user.role is UserRole.ADMIN
            and self.repository.count_active_admins(exclude_id=user.id) == 0
        ):
            raise BusinessRuleError("At least one active admin must remain.")
        if self.repository.has_linked_records(user.id):
            raise ConflictError(
                "This user has defect or activity history and can't be deleted. "
                "Deactivate the account instead."
            )

        username = user.username
        self.activity.log(
            entity_type="user",
            entity_id=user.id,
            actor=actor,
            action=ActivityAction.DELETED,
            old_value=username,
            note=f"Deleted user '{username}'",
        )
        self.repository.delete(user)
        self.commit()
        return username

    def reset_password(self, *, actor: User, user_id: int, new_password: str) -> User:
        user = self.repository.get_or_raise(user_id)
        self._validate_password(new_password)
        user.set_password(new_password)
        self.activity.log(
            entity_type="user",
            entity_id=user.id,
            actor=actor,
            action=ActivityAction.UPDATED,
            field="password",
            note="Password reset by administrator",
        )
        self.commit()
        return user

    # -- invariants ------------------------------------------------------------
    @staticmethod
    def _validate_password(password: str) -> None:
        if len(password or "") < MIN_PASSWORD_LENGTH:
            raise ValidationError(
                f"Password must be at least {MIN_PASSWORD_LENGTH} characters."
            )

    def _guard_admin_invariants(
        self, *, actor: User, target: User, new_role: UserRole, new_active: bool
    ) -> None:
        if target.id == actor.id and not new_active:
            raise BusinessRuleError("You cannot deactivate your own account.")
        if (
            target.id == actor.id
            and target.role is UserRole.ADMIN
            and new_role is not UserRole.ADMIN
        ):
            raise BusinessRuleError("You cannot remove your own admin role.")
        loses_admin = target.role is UserRole.ADMIN and (
            new_role is not UserRole.ADMIN or not new_active
        )
        if loses_admin and self.repository.count_active_admins(exclude_id=target.id) == 0:
            raise BusinessRuleError("At least one active admin must remain.")
