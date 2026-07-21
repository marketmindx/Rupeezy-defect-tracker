"""Application factory.

Everything is wired here: configuration, logging, extensions, blueprints and
error handlers. Extensions live in :mod:`app.extensions` so models and
repositories can import ``db`` without importing this module back.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from flask import Flask

import app.models  # noqa: F401  — registers every mapper and the user loader
from app.cli import register_cli
from app.error_handlers import register_error_handlers
from app.extensions import csrf, db, login_manager, migrate
from app.routes import register_blueprints
from app.utils.logging import configure_logging
from app.utils.security import register_login_guard
from app.utils.templating import register_template_utils
from config import get_config

__all__ = ["create_app"]


def create_app(config_name: str | None = None) -> Flask:
    """Create and fully configure an application instance.

    Args:
        config_name: ``"development"``, ``"testing"`` or ``"production"``.
            Defaults to the ``APP_ENV`` environment variable.

    Returns:
        A ready-to-serve :class:`flask.Flask` application.
    """
    config_cls = get_config(config_name)

    app = Flask(__name__)
    app.config.from_object(config_cls)
    config_cls.init_app(app)

    _ensure_runtime_dirs(app)
    configure_logging(app)
    _init_extensions(app)
    register_blueprints(app)
    register_error_handlers(app)
    register_login_guard(app)
    register_template_utils(app)
    register_cli(app)
    _register_template_context(app)

    app.logger.info(
        "%s v%s initialised (config=%s, db=%s)",
        app.config["APP_NAME"],
        app.config["APP_VERSION"],
        app.config["CONFIG_NAME"],
        _db_backend(app),
    )
    return app


def _init_extensions(app: Flask) -> None:
    db.init_app(app)
    # render_as_batch lets Alembic ALTER SQLite tables by rebuilding them;
    # the directive is transparent on PostgreSQL, so migrations stay portable.
    migrate.init_app(app, db, render_as_batch=True)
    login_manager.init_app(app)
    csrf.init_app(app)


def _ensure_runtime_dirs(app: Flask) -> None:
    """Create writable directories the app expects at runtime."""
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)
    if not app.testing:
        Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)


def _register_template_context(app: Flask) -> None:
    @app.context_processor
    def _inject_globals() -> dict[str, Any]:
        return {"app_env": app.config["CONFIG_NAME"]}


def _db_backend(app: Flask) -> str:
    """Backend scheme for logging — never the full URI (credentials)."""
    uri: str = app.config["SQLALCHEMY_DATABASE_URI"]
    return uri.split("://", 1)[0]
