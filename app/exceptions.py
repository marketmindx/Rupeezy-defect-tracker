"""Domain exception hierarchy.

Services raise these; the global error handlers translate them into a flash +
redirect for web requests or the standard JSON envelope for ``/api/`` requests.
Routes and services stay free of HTTP response code plumbing.
"""
from __future__ import annotations

from typing import Any


class AppError(Exception):
    """Base class for all *expected* application errors."""

    status_code: int = 400
    error_code: str = "bad_request"
    default_message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.details = details
        super().__init__(self.message)


class ValidationError(AppError):
    """Input failed service-layer validation."""

    status_code = 400
    error_code = "validation_error"
    default_message = "Invalid input."


class AuthenticationError(AppError):
    """The caller is not authenticated."""

    status_code = 401
    error_code = "authentication_required"
    default_message = "Authentication is required."


class PermissionDeniedError(AppError):
    """The caller is authenticated but not allowed to do this."""

    status_code = 403
    error_code = "forbidden"
    default_message = "You don't have permission to perform this action."


class NotFoundError(AppError):
    """The requested entity does not exist."""

    status_code = 404
    error_code = "not_found"
    default_message = "The requested resource was not found."


class ConflictError(AppError):
    """The request conflicts with current state (e.g. duplicate)."""

    status_code = 409
    error_code = "conflict"
    default_message = "The request conflicts with the current state."


class BusinessRuleError(AppError):
    """A workflow rule was violated (e.g. an illegal status transition)."""

    status_code = 422
    error_code = "business_rule_violation"
    default_message = "This operation violates a workflow rule."
