"""Shared pytest fixtures: a fresh app + in-memory database per test."""
from __future__ import annotations

from typing import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient

from app import create_app
from app.extensions import db


@pytest.fixture()
def app(tmp_path) -> Iterator[Flask]:
    """Application bound to an in-memory SQLite DB, torn down after each test.

    Note: requests made by test clients REUSE this pushed app context, so
    per-context state (``g``, Flask-Login's current-user cache) is shared
    across every request in a test. Consequence: use one test client per
    test, and switch identities by logging out/in — a second client would
    silently inherit the first client's cached ``current_user``.
    """
    application = create_app("testing")
    application.config["UPLOAD_FOLDER"] = str(tmp_path / "uploads")  # per-test isolation
    with application.app_context():
        db.create_all()
        yield application
        db.session.remove()
        db.drop_all()


@pytest.fixture()
def client(app: Flask) -> FlaskClient:
    return app.test_client()
