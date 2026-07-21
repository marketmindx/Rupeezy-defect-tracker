"""Authentication logic."""
from __future__ import annotations

from typing import Optional

from app.exceptions import AuthenticationError
from app.models import User
from app.repositories.users import UserRepository
from app.services.base import BaseService
from app.utils.datetime import utcnow


class AuthService(BaseService):
    def __init__(self, repository: Optional[UserRepository] = None) -> None:
        self.repository = repository or UserRepository()

    def authenticate(self, identifier: str, password: str) -> User:
        """Verify credentials and record the sign-in.

        The same message covers unknown identifier and wrong password so
        the login form can't be used to enumerate accounts.
        """
        user = self.repository.find_by_identifier(identifier)
        if user is None or not user.check_password(password or ""):
            raise AuthenticationError("Invalid username/email or password.")
        if not user.is_active:
            raise AuthenticationError(
                "This account has been deactivated. Contact an administrator."
            )
        user.last_login_at = utcnow()
        self.commit()
        return user
