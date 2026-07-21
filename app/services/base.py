"""Service-layer base — owns transaction boundaries."""
from __future__ import annotations

from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from app.extensions import db


class BaseService:
    """Base class for application services.

    Routes call services; services call repositories and decide when the
    unit of work commits. Keeping commits out of repositories means one
    request can span several repository calls and still be atomic.
    """

    @staticmethod
    def commit() -> None:
        """Commit the current unit of work, rolling back on failure.

        Re-raises the original error so callers (and the global handlers)
        see the real failure rather than a half-committed session.
        """
        try:
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Commit failed — session rolled back")
            raise
