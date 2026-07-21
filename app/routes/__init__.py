"""Blueprint registry.

Each functional module ships its own blueprint; registering them all here
keeps :func:`app.create_app` free of per-module imports.
"""
from __future__ import annotations

from flask import Flask


def register_blueprints(app: Flask) -> None:
    """Attach every blueprint to the application."""
    from app.routes.auth import auth_bp
    from app.routes.dashboard import dashboard_bp
    from app.routes.defects import defects_bp
    from app.routes.developers import developers_bp
    from app.routes.main import main_bp
    from app.routes.reports import reports_bp
    from app.routes.sprints import sprints_bp
    from app.routes.users import users_bp

    app.register_blueprint(main_bp)
    app.register_blueprint(auth_bp)
    app.register_blueprint(dashboard_bp)
    app.register_blueprint(defects_bp)
    app.register_blueprint(developers_bp)
    app.register_blueprint(reports_bp)
    app.register_blueprint(sprints_bp)
    app.register_blueprint(users_bp)

    # Wired in as their phases land:
    #   sprints_bp    (Phase 6)  — /sprints     sprints, stories, tree view
    #   developers_bp (Phase 7)  — /developers  profiles, workload
    #   reports_bp    (Phase 8)  — /reports     CSV / Excel / PDF exports
    #   api_bp        (Phase 9)  — /api/v1      automation REST API
