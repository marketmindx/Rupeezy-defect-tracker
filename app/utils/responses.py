"""JSON response envelope.

Mirrors the ``{"success": ..., "data": ..., "error": ...}`` convention used
across Rupeezy backend services, so automation tooling gets an identical
shape from this tracker and from the services it tests.
"""
from __future__ import annotations

from typing import Any

from flask import Response, jsonify


def api_success(
    data: Any = None,
    status: int = 200,
    *,
    meta: dict[str, Any] | None = None,
) -> tuple[Response, int]:
    """Build a success envelope; ``meta`` carries pagination info later."""
    body: dict[str, Any] = {"success": True, "data": data, "error": None}
    if meta is not None:
        body["meta"] = meta
    return jsonify(body), status


def api_error(
    message: str,
    *,
    code: str = "error",
    status: int = 400,
    details: dict[str, Any] | None = None,
) -> tuple[Response, int]:
    """Build an error envelope with a machine-readable ``code``."""
    error: dict[str, Any] = {"code": code, "message": message}
    if details:
        error["details"] = details
    return jsonify({"success": False, "data": None, "error": error}), status
