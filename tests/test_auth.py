"""Phase 3 auth tests: login/logout, the login guard, remember-me, role guard."""
from __future__ import annotations

from app.models.enums import UserRole
from tests.factories import login, make_user


class TestLogin:
    def test_login_page_is_public(self, client) -> None:
        response = client.get("/auth/login")
        assert response.status_code == 200
        assert b"Sign in" in response.data

    def test_login_with_username(self, client) -> None:
        user = make_user()
        response = login(client, user)
        assert b"Welcome back" in response.data
        assert client.get("/dashboard/").status_code == 200

    def test_login_with_email(self, client) -> None:
        user = make_user()
        response = client.post(
            "/auth/login",
            data={"identifier": user.email, "password": "Secret@123"},
            follow_redirects=True,
        )
        assert b"Welcome back" in response.data

    def test_wrong_password_rejected(self, client) -> None:
        user = make_user()
        response = client.post(
            "/auth/login",
            data={"identifier": user.username, "password": "nope-nope"},
            follow_redirects=True,
        )
        assert b"Invalid username/email or password." in response.data
        assert client.get("/dashboard/").status_code == 302  # still anonymous

    def test_inactive_account_blocked(self, client) -> None:
        user = make_user(is_active=False)
        response = client.post(
            "/auth/login",
            data={"identifier": user.username, "password": "Secret@123"},
            follow_redirects=True,
        )
        assert b"deactivated" in response.data

    def test_last_login_recorded(self, client) -> None:
        user = make_user()
        assert user.last_login_at is None
        login(client, user)
        assert user.last_login_at is not None

    def test_remember_cookie_set_when_requested(self, client) -> None:
        user = make_user()
        client.post(
            "/auth/login",
            data={"identifier": user.username, "password": "Secret@123", "remember_me": "y"},
        )
        assert client.get_cookie("remember_token") is not None

    def test_no_remember_cookie_by_default(self, client) -> None:
        user = make_user()
        client.post(
            "/auth/login",
            data={"identifier": user.username, "password": "Secret@123"},
        )
        assert client.get_cookie("remember_token") is None

    def test_logout(self, client) -> None:
        user = make_user()
        login(client, user)
        response = client.post("/auth/logout", follow_redirects=True)
        assert b"Signed out." in response.data
        assert client.get("/dashboard/").status_code == 302

    def test_login_page_redirects_when_already_signed_in(self, client) -> None:
        user = make_user()
        login(client, user)
        assert client.get("/auth/login").status_code == 302


class TestLoginGuard:
    def test_anonymous_redirected_with_next(self, client) -> None:
        response = client.get("/users/")
        assert response.status_code == 302
        location = response.headers["Location"]
        assert "/auth/login" in location
        assert "next=" in location

    def test_next_param_honoured(self, client) -> None:
        admin = make_user(role=UserRole.ADMIN)
        response = client.post(
            "/auth/login?next=/users/",
            data={"identifier": admin.username, "password": "Secret@123"},
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/users/"

    def test_unsafe_next_rejected(self, client) -> None:
        user = make_user()
        response = client.post(
            "/auth/login?next=https://evil.example/phish",
            data={"identifier": user.username, "password": "Secret@123"},
        )
        assert response.status_code == 302
        assert response.headers["Location"] == "/"

    def test_protected_api_route_returns_401_envelope(self, app) -> None:
        @app.get("/api/v1/_ping")
        def ping():  # pragma: no cover — test helper route
            return {"pong": True}

        response = app.test_client().get("/api/v1/_ping")
        assert response.status_code == 401
        body = response.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "authentication_required"


class TestRoleGuard:
    def test_admin_area_forbidden_for_qa(self, client) -> None:
        login(client, make_user(role=UserRole.QA))
        response = client.get("/users/")
        assert response.status_code == 403
        assert b"Access denied" in response.data

    def test_admin_area_forbidden_for_developer(self, client) -> None:
        login(client, make_user(role=UserRole.DEVELOPER))
        assert client.get("/users/").status_code == 403

    def test_admin_area_allowed_for_admin(self, client) -> None:
        login(client, make_user(role=UserRole.ADMIN))
        response = client.get("/users/")
        assert response.status_code == 200
        assert b"User management" in response.data
