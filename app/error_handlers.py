"""Centralised error handling.

Web requests get flash messages or rendered error pages; anything under
``/api/`` (or explicitly asking for JSON) gets the standard envelope — the
same shape the Phase 9 automation API will use, so Appium/Playwright/Postman
clients can rely on one error format everywhere.
"""
from __future__ import annotations

from flask import Flask, flash, redirect, render_template, request, url_for

from app.exceptions import AppError
from app.extensions import db
from app.utils.responses import api_error


def register_error_handlers(app: Flask) -> None:
    """Attach application-wide error handlers to ``app``."""

    def wants_json() -> bool:
        if request.path.startswith("/api/"):
            return True
        best = request.accept_mimetypes.best_match(["application/json", "text/html"])
        return best == "application/json"

    def error_page(status: int, title: str, message: str):
        return (
            render_template("errors/error.html", code=status, title=title, message=message),
            status,
        )

    @app.errorhandler(AppError)
    def handle_app_error(exc: AppError):
        if wants_json():
            return api_error(
                exc.message,
                code=exc.error_code,
                status=exc.status_code,
                details=exc.details,
            )
        flash(exc.message, "danger")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(403)
    def handle_403(_exc):
        if wants_json():
            return api_error("You don't have permission to do that.", code="forbidden", status=403)
        return error_page(403, "Access denied", "You don't have permission to view this page.")

    @app.errorhandler(404)
    def handle_404(_exc):
        if wants_json():
            return api_error(
                "The requested resource was not found.",
                code="not_found",
                status=404,
                details={"path": request.path},
            )
        return error_page(404, "Page not found", "The page you're looking for doesn't exist or was moved.")

    @app.errorhandler(413)
    def handle_413(_exc):
        limit_mb = app.config["MAX_CONTENT_LENGTH"] // (1024 * 1024)
        message = f"Upload exceeds the {limit_mb} MB limit."
        if wants_json():
            return api_error(message, code="payload_too_large", status=413)
        flash(message, "danger")
        return redirect(request.referrer or url_for("main.index"))

    @app.errorhandler(500)
    def handle_500(exc):
        # Never leave a broken session behind for the next request.
        db.session.rollback()
        original = getattr(exc, "original_exception", exc)
        app.logger.error("Unhandled server error: %s", original, exc_info=original)
        if wants_json():
            return api_error("Internal server error.", code="internal_error", status=500)
        return error_page(500, "Something went wrong", "The error has been logged. Please try again.")
