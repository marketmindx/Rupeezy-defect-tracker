"""Phase 3 admin user-management tests: CRUD, audit trail, invariants."""
from __future__ import annotations

from typing import List

import pytest
import sqlalchemy as sa

from app.exceptions import BusinessRuleError
from app.extensions import db
from app.models import ActivityAction, ActivityLog, User
from app.models.enums import UserRole
from app.services.users import UserService
from tests.factories import login, make_defect, make_module, make_user


@pytest.fixture()
def admin(app) -> User:
    return make_user(role=UserRole.ADMIN, username="boss")


@pytest.fixture()
def admin_client(client, admin):
    login(client, admin)
    return client


def _activity_rows(user_id: int) -> "List[ActivityLog]":
    return list(
        db.session.scalars(
            sa.select(ActivityLog).where(
                ActivityLog.entity_type == "user", ActivityLog.entity_id == user_id
            )
        )
    )


class TestUserList:
    def test_search_and_filters(self, admin_client) -> None:
        make_user(username="alice", full_name="Alice A")
        make_user(username="bob", full_name="Bob B", role=UserRole.DEVELOPER, is_active=False)

        page = admin_client.get("/users/?q=alice")
        assert b"alice" in page.data
        assert b"bob" not in page.data

        page = admin_client.get("/users/?role=DEVELOPER")
        assert b"bob" in page.data
        assert b"alice" not in page.data

        page = admin_client.get("/users/?status=inactive")
        assert b"bob" in page.data
        assert b"alice" not in page.data

    def test_pagination(self, admin_client) -> None:
        for _ in range(25):
            make_user()
        page2 = admin_client.get("/users/?page=2")
        assert page2.status_code == 200
        assert b"Showing 21" in page2.data  # 26 users -> 20 on page 1, 6 on page 2


class TestCreateUser:
    @staticmethod
    def _form(**overrides) -> dict:
        data = {
            "username": "new.qa",
            "email": "new.qa@example.com",
            "full_name": "New Tester",
            "role": "QA",
            "password": "Testpass@1",
            "confirm_password": "Testpass@1",
            "is_active": "y",
        }
        data.update(overrides)
        return data

    def test_create_success_with_audit(self, admin_client) -> None:
        response = admin_client.post("/users/new", data=self._form(), follow_redirects=True)
        assert b"created" in response.data

        user = db.session.scalar(sa.select(User).where(User.username == "new.qa"))
        assert user is not None
        assert user.role is UserRole.QA
        assert user.check_password("Testpass@1")
        assert any(r.action is ActivityAction.CREATED for r in _activity_rows(user.id))

    def test_duplicate_username_rejected(self, admin_client) -> None:
        make_user(username="taken")
        response = admin_client.post("/users/new", data=self._form(username="taken"))
        assert b"already taken" in response.data

    def test_short_password_rejected_by_form(self, admin_client) -> None:
        response = admin_client.post(
            "/users/new", data=self._form(password="abc", confirm_password="abc")
        )
        assert b"At least 8 characters." in response.data


class TestEditUser:
    def test_update_fields_with_field_level_audit(self, admin_client) -> None:
        target = make_user()
        response = admin_client.post(
            f"/users/{target.id}/edit",
            data={
                "username": target.username,
                "email": "renamed@example.com",
                "full_name": "Renamed Person",
                "role": "DEVELOPER",
                "is_active": "y",
            },
            follow_redirects=True,
        )
        assert b"Profile updated." in response.data
        assert target.role is UserRole.DEVELOPER
        assert target.email == "renamed@example.com"

        fields = {
            r.field for r in _activity_rows(target.id) if r.action is ActivityAction.UPDATED
        }
        assert {"email", "full_name", "role"} <= fields

    def test_cannot_demote_self(self, admin_client, admin) -> None:
        response = admin_client.post(
            f"/users/{admin.id}/edit",
            data={
                "username": admin.username,
                "email": admin.email,
                "full_name": admin.full_name,
                "role": "QA",
                "is_active": "y",
            },
            follow_redirects=True,
        )
        assert b"cannot remove your own admin role" in response.data
        assert admin.role is UserRole.ADMIN

    def test_last_active_admin_protected_at_service_level(self, app, admin) -> None:
        # Only reachable with a non-active actor (e.g. future automation),
        # so exercised directly against the service layer.
        inactive_admin = make_user(role=UserRole.ADMIN, is_active=False)
        with pytest.raises(BusinessRuleError, match="At least one active admin"):
            UserService().update_profile(
                actor=inactive_admin,
                user_id=admin.id,
                username=admin.username,
                email=admin.email,
                full_name=admin.full_name,
                role=UserRole.QA,
                is_active=True,
            )


class TestUsernameRename:
    @staticmethod
    def _edit_data(user, **overrides) -> dict:
        data = {
            "username": user.username,
            "email": user.email,
            "full_name": user.full_name,
            "role": user.role.name,
            "is_active": "y",
        }
        data.update(overrides)
        return data

    def test_rename_updates_login_and_audit(self, admin_client) -> None:
        target = make_user(full_name="Krishna Pal")
        response = admin_client.post(
            f"/users/{target.id}/edit",
            data=self._edit_data(target, username="krishna.pal"),
            follow_redirects=True,
        )
        assert b"Profile updated." in response.data
        assert "Sign-in username changed".encode() in response.data
        assert target.username == "krishna.pal"

        row = next(r for r in _activity_rows(target.id) if r.field == "username")
        assert row.new_value == "krishna.pal"

        # Old username stops working; the new one signs in.
        admin_client.post("/auth/logout")
        old = admin_client.post(
            "/auth/login",
            data={"identifier": row.old_value, "password": "Secret@123"},
            follow_redirects=True,
        )
        assert b"Sign in" in old.data  # still on the login page
        fresh = login(admin_client, target)
        assert b"Dashboard" in fresh.data

    def test_rename_to_taken_username_rejected(self, admin_client) -> None:
        make_user(username="occupied")
        target = make_user()
        before = target.username
        response = admin_client.post(
            f"/users/{target.id}/edit",
            data=self._edit_data(target, username="OCCUPIED"),  # case-insensitive
            follow_redirects=True,
        )
        assert b"already taken" in response.data
        assert target.username == before

    def test_rename_bad_format_rejected(self, admin_client) -> None:
        target = make_user()
        response = admin_client.post(
            f"/users/{target.id}/edit",
            data=self._edit_data(target, username="bad name!"),
        )
        assert b"Letters, digits, dots, dashes and underscores only." in response.data


class TestToggleActive:
    def test_deactivate_then_login_blocked(self, admin_client) -> None:
        target = make_user()
        response = admin_client.post(
            f"/users/{target.id}/toggle-active", follow_redirects=True
        )
        assert b"deactivated" in response.data
        assert target.is_active is False

        # Same client, signed out first — see the conftest note on why a
        # second test client must not be mixed into one test.
        admin_client.post("/auth/logout")
        blocked = admin_client.post(
            "/auth/login",
            data={"identifier": target.username, "password": "Secret@123"},
            follow_redirects=True,
        )
        assert b"deactivated" in blocked.data

    def test_cannot_deactivate_self(self, admin_client, admin) -> None:
        response = admin_client.post(
            f"/users/{admin.id}/toggle-active", follow_redirects=True
        )
        assert b"cannot deactivate your own account" in response.data
        assert admin.is_active is True


class TestDeleteUser:
    def test_delete_clean_user_with_audit(self, admin_client) -> None:
        target = make_user(username="disposable")
        target_id = target.id

        response = admin_client.post(
            f"/users/{target_id}/delete", follow_redirects=True
        )
        assert b"deleted" in response.data
        assert db.session.get(User, target_id) is None
        # The DELETED audit row survives the user it refers to.
        assert any(r.action is ActivityAction.DELETED for r in _activity_rows(target_id))

    def test_cannot_delete_self(self, admin_client, admin) -> None:
        response = admin_client.post(
            f"/users/{admin.id}/delete", follow_redirects=True
        )
        assert b"cannot delete your own account" in response.data
        assert db.session.get(User, admin.id) is not None

    def test_user_with_history_cannot_be_deleted(self, admin_client) -> None:
        reporter = make_user(username="hasbugs")
        make_defect(reporter=reporter, module=make_module())

        response = admin_client.post(
            f"/users/{reporter.id}/delete", follow_redirects=True
        )
        assert b"Deactivate the account instead" in response.data
        assert db.session.get(User, reporter.id) is not None

    def test_last_active_admin_protected(self, app, admin) -> None:
        # Reachable only with a non-active actor, so exercised at the service layer.
        inactive_admin = make_user(role=UserRole.ADMIN, is_active=False)
        with pytest.raises(BusinessRuleError, match="At least one active admin"):
            UserService().delete_user(actor=inactive_admin, user_id=admin.id)


class TestPasswordReset:
    def test_reset_password_with_audit(self, admin_client) -> None:
        target = make_user()
        response = admin_client.post(
            f"/users/{target.id}/password",
            data={"password": "Brandnew@9", "confirm_password": "Brandnew@9"},
            follow_redirects=True,
        )
        assert b"Password reset." in response.data
        assert target.check_password("Brandnew@9")
        assert not target.check_password("Secret@123")
        assert any(r.field == "password" for r in _activity_rows(target.id))
