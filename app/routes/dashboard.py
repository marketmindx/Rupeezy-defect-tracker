"""Dashboard blueprint."""
from __future__ import annotations

from flask import Blueprint, render_template

from app.services.dashboard import DashboardService

dashboard_bp = Blueprint("dashboard", __name__, url_prefix="/dashboard")


@dashboard_bp.get("/")
def overview():
    """Quality overview: tiles, charts, sprint progress, activity."""
    return render_template("dashboard/overview.html", **DashboardService().overview())
