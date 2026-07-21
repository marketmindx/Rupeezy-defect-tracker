"""Authentication/authorization plumbing.

The app is secure by default: :func:`register_login_guard` requires a signed-in
user for **every** route, so blueprints added in later phases are protected the
moment they're registered. Views that must stay reachable anonymously (login,
health probe) opt out explicitly with :func:`public_route`.
"""
from __future__ import annotations

from functools import wraps
from typing import Callable, Optional, TypeVar
from urllib.parse import urlsplit

from flask import Flask, abort, request
from flask_login import current_user

from app.extensions import login_manager
from app.models.enums import UserRole
from app.utils.responses import api_error

ViewT = TypeVar("ViewT", bound=Callable)


def public_route(view: ViewT) -> ViewT:
    """Mark a view as reachable without authentication."""
    view.is_public = True  # type: ignore[attr-defined]
    return view


def register_login_guard(app: Flask) -> None:
    @app.before_request
    def _require_login():  # type: ignore[reportUnusedFunction]
        endpoint = request.endpoint
        if endpoint is None:  # no route matched — let 404/405 handling run
            return None
        if endpoint == "static":
            return None
        view = app.view_functions.get(endpoint)
        if view is not None and getattr(view, "is_public", False):
            return None
        if current_user.is_authenticated:
            return None
        if request.path.startswith("/api/"):
            return api_error(
                "Authentication required.", code="authentication_required", status=401
            )
        return login_manager.unauthorized()


def role_required(*roles: UserRole) -> "Callable[[ViewT], ViewT]":
    """403 unless the current user's role is one of ``roles``."""

    def decorator(view: ViewT) -> ViewT:
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not current_user.is_authenticated:  # login guard runs first; belt & braces
                return login_manager.unauthorized()
            if current_user.role not in roles:
                abort(403)
            return view(*args, **kwargs)

        return wrapped  # type: ignore[return-value]

    return decorator


admin_required = role_required(UserRole.ADMIN)


def safe_next_url(target: Optional[str]) -> Optional[str]:
    """Return ``target`` only if it is a local path (open-redirect guard)."""
    if not target:
        return None
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return None
    if not target.startswith("/") or target.startswith("//"):
        return None
    return target
