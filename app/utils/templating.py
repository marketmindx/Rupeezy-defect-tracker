"""Jinja filters and globals."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from flask import Flask, current_app

from app.utils.datetime import utcnow


def register_template_utils(app: Flask) -> None:
    @app.template_filter("localdt")
    def localdt(value: Optional[datetime], fmt: str = "%d %b %Y · %H:%M") -> str:
        """Render a naive-UTC timestamp in the machine's local timezone."""
        if value is None:
            return "—"
        return value.replace(tzinfo=timezone.utc).astimezone().strftime(fmt)

    @app.template_filter("timeago")
    def timeago(value: Optional[datetime]) -> str:
        """Compact relative time for feeds ("just now", "3h ago", "2d ago")."""
        if value is None:
            return "—"
        seconds = max(int((utcnow() - value).total_seconds()), 0)
        if seconds < 60:
            return "just now"
        if seconds < 3600:
            return f"{seconds // 60}m ago"
        if seconds < 86400:
            return f"{seconds // 3600}h ago"
        days = seconds // 86400
        if days < 7:
            return f"{days}d ago"
        return value.replace(tzinfo=timezone.utc).astimezone().strftime("%d %b %Y")

    @app.template_filter("humansize")
    def humansize(num_bytes) -> str:
        """1234567 → \"1.2 MB\" for attachment listings."""
        size = float(num_bytes or 0)
        for unit in ("B", "KB", "MB", "GB"):
            if size < 1024 or unit == "GB":
                return f"{size:.0f} {unit}" if unit == "B" else f"{size:.1f} {unit}"
            size /= 1024
        return f"{size:.1f} GB"  # pragma: no cover — loop always returns

    @app.template_global("endpoint_exists")
    def endpoint_exists(endpoint: str) -> bool:
        """True once a (future phase's) endpoint has been registered.

        Lets scaffolding like dashboard quick-filters render as disabled
        chips today and become live links the moment their module lands.
        """
        return endpoint in current_app.view_functions
