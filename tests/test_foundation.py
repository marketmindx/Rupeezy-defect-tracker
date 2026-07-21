"""Phase 1 smoke tests: factory, config selection, health probe, error paths."""
from __future__ import annotations

import os

import pytest

from app import create_app
from tests.factories import login, make_user


class TestAppFactory:
    def test_testing_config_is_applied(self, app) -> None:
        assert app.testing is True
        assert app.config["SQLALCHEMY_DATABASE_URI"] == "sqlite://"
        assert app.config["CONFIG_NAME"] == "testing"

    def test_unknown_config_name_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="Unknown APP_ENV"):
            create_app("staging")

    @pytest.mark.skipif(
        bool(os.getenv("SECRET_KEY")),
        reason="a real SECRET_KEY is configured in this environment",
    )
    def test_production_refuses_to_boot_without_secret_key(self) -> None:
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            create_app("production")


class TestHealth:
    def test_health_reports_up(self, client) -> None:
        response = client.get("/health")
        assert response.status_code == 200
        body = response.get_json()
        assert body["success"] is True
        assert body["error"] is None
        assert body["data"]["database"] == "up"
        assert body["data"]["environment"] == "testing"


class TestShellAndErrors:
    def test_index_requires_login(self, client) -> None:
        response = client.get("/")
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_index_redirects_signed_in_users_to_dashboard(self, client) -> None:
        login(client, make_user())
        response = client.get("/")
        assert response.status_code == 302
        assert "/dashboard/" in response.headers["Location"]

    def test_unknown_page_renders_html_404(self, client) -> None:
        response = client.get("/definitely-not-a-page")
        assert response.status_code == 404
        assert b"Page not found" in response.data

    def test_unknown_api_path_returns_json_envelope(self, client) -> None:
        response = client.get("/api/v1/definitely-not-there")
        assert response.status_code == 404
        body = response.get_json()
        assert body["success"] is False
        assert body["data"] is None
        assert body["error"]["code"] == "not_found"
        assert body["error"]["details"]["path"] == "/api/v1/definitely-not-there"

    def test_app_error_maps_to_envelope_on_api_paths(self, app) -> None:
        from app.exceptions import ConflictError
        from app.utils.security import public_route

        @app.get("/api/v1/_boom")
        @public_route
        def boom():  # pragma: no cover — test helper route
            raise ConflictError("Duplicate bug id.")

        response = app.test_client().get("/api/v1/_boom")
        assert response.status_code == 409
        body = response.get_json()
        assert body["success"] is False
        assert body["error"]["code"] == "conflict"
        assert body["error"]["message"] == "Duplicate bug id."

    def test_app_error_flashes_and_redirects_on_web_paths(self, app) -> None:
        from app.exceptions import PermissionDeniedError
        from app.utils.security import public_route

        @app.get("/_forbidden")
        @public_route
        def forbidden():  # pragma: no cover — test helper route
            raise PermissionDeniedError()

        client = app.test_client()
        # AppError -> flash + redirect to index -> login guard -> login page,
        # where the flashed message is rendered.
        response = client.get("/_forbidden", follow_redirects=True)
        assert response.status_code == 200
        assert b"permission" in response.data.lower()
