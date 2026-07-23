"""Dashboard blueprint."""
from __future__ import annotations

from flask import Blueprint, render_template
from flask_login import current_user

from app.services.dashboard import DashboardService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
def overview():
    """Quality overview: tiles, charts, sprint progress, activity.

    Scoped to the signed-in user's own defects (admins see everything).
    """
    return render_template(
        "dashboard/overview.html", **DashboardService(current_user).overview()
    )
