"""Root routes: home redirect and health probe."""
from __future__ import annotations

from flask import Blueprint, current_app, redirect, url_for

import sqlalchemy as sa

from app.extensions import db
from app.utils.responses import api_error, api_success
from app.utils.security import public_route

main_bp = Blueprint("main", __name__)


@main_bp.get("/")
def index():
    """Canonical home endpoint — forwards to the dashboard."""
    return redirect(url_for("dashboard.overview"))


def _database_reachable() -> bool:
    try:
        db.session.execute(sa.text("SELECT 1"))
        return True
    except Exception:  # pragma: no cover — exercised only on real outages
        current_app.logger.exception("Database health check failed")
        return False


@main_bp.get("/health")
@public_route
def health():
    """Liveness/readiness probe returning the standard JSON envelope."""
    db_ok = _database_reachable()
    data = {
        "app": current_app.config["APP_NAME"],
        "version": current_app.config["APP_VERSION"],
        "environment": current_app.config["CONFIG_NAME"],
        "database": "up" if db_ok else "down",
    }
    if db_ok:
        return api_success(data)
    return api_error("Database unreachable.", code="database_down", status=503, details=data)
