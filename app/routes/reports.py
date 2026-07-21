"""Reports hub, CSV exports (Google Sheets-ready) and PDF documents."""
from __future__ import annotations

from datetime import date

import sqlalchemy as sa
from flask import Blueprint, Response, render_template
from flask_login import current_user

from app.extensions import db
from app.models import Severity, Sprint
# Single source of truth for list filters — reports must accept exactly
# the same query params as /defects/.
from app.routes.defects import _parse_filters
from app.services.reports import ReportService

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")


def _csv_response(payload: str, stem: str) -> Response:
    filename = f"{stem}_{date.today():%Y-%m-%d}.csv"
    return Response(
        payload,
        mimetype="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


def _pdf_response(payload: bytes, stem: str) -> Response:
    filename = f"{stem}_{date.today():%Y-%m-%d}.pdf"
    return Response(
        payload,
        mimetype="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{filename}"'},
    )


@reports_bp.get("/")
def index():
    sprints = list(
        db.session.scalars(sa.select(Sprint).order_by(Sprint.number.desc()).limit(24))
    )
    return render_template(
        "reports/index.html", sprints=sprints, severities=list(Severity)
    )


@reports_bp.get("/defects.csv")
def defects_csv():
    return _csv_response(ReportService().defects_csv(_parse_filters()), "defects")


@reports_bp.get("/developers.csv")
def developers_csv():
    return _csv_response(ReportService().developers_csv(), "team_workload")


@reports_bp.get("/summary.pdf")
def summary_pdf():
    return _pdf_response(ReportService().summary_pdf(actor=current_user), "qa_summary")


@reports_bp.get("/sprint/<int:sprint_id>.pdf")
def sprint_pdf(sprint_id: int):
    return _pdf_response(
        ReportService().sprint_pdf(sprint_id, actor=current_user),
        f"sprint_{sprint_id}_report",
    )
