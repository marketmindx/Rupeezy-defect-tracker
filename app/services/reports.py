"""Report generation: CSV exports (Google Sheets-ready) and PDF documents.

CSVs are plain UTF-8 with a BOM so both Google Sheets and Excel open them
with correct characters (₹, names, …). PDFs are built with reportlab —
pure Python, fully offline.
"""
from __future__ import annotations

import csv
import io
from datetime import date
from typing import List, Optional

from reportlab.graphics.charts.barcharts import VerticalBarChart
from reportlab.graphics.shapes import Drawing
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

from app.models import Defect, DefectStatus, Severity, User
from app.repositories.defects import DefectFilters, DefectRepository
from app.repositories.developers import DeveloperRepository
from app.services.agile import SprintService
from app.services.base import BaseService
from app.utils.datetime import utcnow

CSV_BOM = "\ufeff"

_SEVERITY_HEX = {
    Severity.CRITICAL: "#dc3545",
    Severity.HIGH: "#ffc107",
    Severity.MEDIUM: "#0dcaf0",
    Severity.LOW: "#198754",
}

_DEFECT_COLUMNS = [
    "Key", "Title", "Status", "Severity", "Priority", "Criticality",
    "Platform", "Environment", "Module", "Feature", "Story", "Sprint",
    "Reporter", "Assigned QA", "Developer", "Labels", "Tags",
    "Regression required", "Regression status", "ETA",
    "App version", "Build", "Device", "OS",
    "Created (UTC)", "Updated (UTC)", "Resolved (UTC)",
    "Resolution", "Duplicate of",
]


def _dt(value) -> str:
    return value.strftime("%Y-%m-%d %H:%M") if value else ""


def _enum(value) -> str:
    return value.value if value else ""


class ReportService(BaseService):
    def __init__(self) -> None:
        self.defects = DefectRepository()
        self.people = DeveloperRepository()

    # ------------------------------------------------------------------ CSV
    def defects_csv(self, filters: DefectFilters) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(_DEFECT_COLUMNS)
        for d in self.defects.list_filtered(filters):
            writer.writerow([
                d.defect_key, d.title, d.status.value, d.severity.value,
                d.priority.value, _enum(d.criticality), d.platform.value,
                d.environment.value, d.module.name,
                d.feature.name if d.feature else "",
                d.story.key if d.story else "",
                d.sprint.name if d.sprint else "",
                d.reporter.full_name,
                d.assigned_qa.full_name if d.assigned_qa else "",
                d.assigned_developer.full_name if d.assigned_developer else "",
                ", ".join(sorted(label.name for label in d.labels)),
                ", ".join(sorted(tag.name for tag in d.tags)),
                "Yes" if d.regression_required else "No",
                _enum(d.regression_status),
                d.eta.isoformat() if d.eta else "",
                d.app_version or "", d.build_number or "",
                d.device_name or "", d.os_version or "",
                _dt(d.created_at), _dt(d.updated_at), _dt(d.resolved_at),
                _enum(d.resolution_type),
                d.duplicate_of.defect_key if d.duplicate_of else "",
            ])
        return CSV_BOM + buffer.getvalue()

    def developers_csv(self) -> str:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow([
            "Name", "Username", "Role", "Active",
            "Open assigned", "Critical open", "High open", "Overdue (ETA)",
            "Resolved all-time", "Assigned all-time", "Avg resolution (days)",
            "Open QA queue", "Reported",
        ])
        from app.models import UserRole

        people: "List[User]" = (
            self.people.users_with_role(UserRole.DEVELOPER)
            + self.people.users_with_role(UserRole.QA)
        )
        for user in people:
            stats = self.people.assignment_stats(user.id)
            avg = self.people.avg_resolution_days(user.id)
            writer.writerow([
                user.full_name, user.username, user.role.value,
                "Yes" if user.is_active else "No",
                stats["open"], stats["critical_open"], stats["high_open"],
                stats["overdue"], stats["done"], stats["assigned_total"],
                avg if avg is not None else "",
                self.people.qa_open_count(user.id),
                self.people.reported_count(user.id),
            ])
        return CSV_BOM + buffer.getvalue()

    # ------------------------------------------------------------------ PDF
    @staticmethod
    def _styles():
        base = getSampleStyleSheet()
        return {
            "title": ParagraphStyle("rz-title", parent=base["Title"], fontSize=20,
                                    spaceAfter=2),
            "meta": ParagraphStyle("rz-meta", parent=base["Normal"], fontSize=9,
                                   textColor=colors.HexColor("#6c757d"), spaceAfter=10),
            "h2": ParagraphStyle("rz-h2", parent=base["Heading2"], fontSize=13,
                                 spaceBefore=14, spaceAfter=6,
                                 textColor=colors.HexColor("#0d6efd")),
            "cell": ParagraphStyle("rz-cell", parent=base["Normal"], fontSize=8),
        }

    @staticmethod
    def _table(data, col_widths=None, header_bg="#0d6efd") -> Table:
        table = Table(data, colWidths=col_widths, repeatRows=1, hAlign="LEFT")
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor(header_bg)),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1),
             [colors.white, colors.HexColor("#f4f6f8")]),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#ced4da")),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        return table

    @staticmethod
    def _severity_chart(counts: "dict") -> Drawing:
        drawing = Drawing(240, 130)
        chart = VerticalBarChart()
        chart.x, chart.y = 25, 20
        chart.width, chart.height = 200, 100
        chart.data = [[counts.get(severity, 0) for severity in Severity]]
        chart.categoryAxis.categoryNames = [severity.value for severity in Severity]
        chart.categoryAxis.labels.fontSize = 7
        chart.valueAxis.valueMin = 0
        chart.valueAxis.labels.fontSize = 7
        chart.bars[0].fillColor = colors.HexColor("#0d6efd")
        for index, severity in enumerate(Severity):
            chart.bars[(0, index)].fillColor = colors.HexColor(_SEVERITY_HEX[severity])
        drawing.add(chart)
        return drawing

    def _doc(self, buffer: io.BytesIO, title: str):
        return SimpleDocTemplate(
            buffer, pagesize=A4, title=title,
            leftMargin=16 * mm, rightMargin=16 * mm,
            topMargin=14 * mm, bottomMargin=14 * mm,
        )

    def _header(self, story: list, styles: dict, title: str, actor: User) -> None:
        story.append(Paragraph(f"Rupeezy Defect Tracker — {title}", styles["title"]))
        story.append(Paragraph(
            f"Generated {utcnow():%d %b %Y %H:%M} UTC · by {actor.full_name}",
            styles["meta"],
        ))

    def summary_pdf(self, *, actor: User) -> bytes:
        from app.repositories.dashboard import DashboardRepository

        dashboard = DashboardRepository()
        styles = self._styles()
        by_status = dashboard.count_by_status()
        total = sum(by_status.values())
        done = sum(count for status, count in by_status.items() if status.is_terminal)
        open_by_severity = dashboard.count_open_by_severity()

        story: list = []
        self._header(story, styles, "QA summary", actor)

        story.append(Paragraph("Overall", styles["h2"]))
        story.append(self._table([
            ["Total defects", "Open", "Completed", "Critical open", "High open"],
            [total, total - done, done,
             open_by_severity.get(Severity.CRITICAL, 0),
             open_by_severity.get(Severity.HIGH, 0)],
        ]))
        story.append(Spacer(1, 6))
        if any(open_by_severity.values()):
            story.append(Paragraph("Open defects by severity", styles["h2"]))
            story.append(self._severity_chart(open_by_severity))

        story.append(Paragraph("Defects by status", styles["h2"]))
        story.append(self._table(
            [["Status", "Count"]]
            + [[status.value, count] for status, count in by_status.items() if count]
        , col_widths=[60 * mm, 25 * mm]))

        sprint = dashboard.current_sprint()
        if sprint:
            sprint_total, sprint_done = dashboard.sprint_stats(sprint.id)
            pct = round(sprint_done * 100 / sprint_total) if sprint_total else 0
            story.append(Paragraph(f"Current sprint — {sprint.name}", styles["h2"]))
            story.append(self._table([
                ["Dates", "Status", "Defects", "Completed", "Completion"],
                [f"{sprint.start_date:%d %b} – {sprint.end_date:%d %b %Y}",
                 sprint.status.value, sprint_total, sprint_done, f"{pct}%"],
            ]))

        story.append(Paragraph("Developer workload", styles["h2"]))
        from app.models import UserRole

        rows = [["Developer", "Open", "Critical", "Resolved", "Avg days"]]
        for user in self.people.users_with_role(UserRole.DEVELOPER):
            stats = self.people.assignment_stats(user.id)
            avg = self.people.avg_resolution_days(user.id)
            rows.append([
                user.full_name, stats["open"], stats["critical_open"],
                stats["done"], avg if avg is not None else "—",
            ])
        story.append(self._table(rows, col_widths=[55 * mm, 20 * mm, 20 * mm, 20 * mm, 22 * mm]))

        story.append(Paragraph("Top open defects", styles["h2"]))
        top = self.defects.list_filtered(
            DefectFilters(state="open", sort="severity", direction="asc"), limit=15
        )
        story.append(self._defect_table(top, styles))

        buffer = io.BytesIO()
        self._doc(buffer, "QA summary").build(story)
        return buffer.getvalue()

    def sprint_pdf(self, sprint_id: int, *, actor: User) -> bytes:
        context = SprintService().detail_context(sprint_id)
        sprint = context["sprint"]
        styles = self._styles()

        story: list = []
        self._header(story, styles, f"Sprint report · {sprint.name}", actor)
        if sprint.goal:
            story.append(Paragraph(f"Goal: {sprint.goal}", styles["meta"]))

        story.append(Paragraph("Sprint metrics", styles["h2"]))
        story.append(self._table([
            ["Dates", "Status", "Defects", "Completed", "Still open", "Completion"],
            [f"{sprint.start_date:%d %b} – {sprint.end_date:%d %b %Y}",
             sprint.status.value, context["total"], context["done"],
             context["open_count"], f"{context['pct']}%"],
        ]))

        breakdown = context["breakdown"]
        if breakdown:
            story.append(Paragraph("Status breakdown", styles["h2"]))
            story.append(self._table(
                [["Status", "Count"]]
                + [[status.value, breakdown[status]]
                   for status in DefectStatus if breakdown.get(status)]
            , col_widths=[60 * mm, 25 * mm]))

        if context["stories"]:
            story.append(Paragraph("Stories", styles["h2"]))
            story.append(self._table(
                [["Story", "Title", "Status", "Points", "Bugs"]]
                + [[s.key, Paragraph(s.title[:80], styles["cell"]),
                    s.status.value, s.story_points or "—", bugs]
                   for s, bugs in context["stories"]],
                col_widths=[24 * mm, 82 * mm, 22 * mm, 16 * mm, 14 * mm],
            ))

        story.append(Paragraph("Defects in sprint", styles["h2"]))
        story.append(self._defect_table(context["defects"], styles))

        buffer = io.BytesIO()
        self._doc(buffer, f"Sprint report {sprint.name}").build(story)
        return buffer.getvalue()

    def _defect_table(self, defects: "List[Defect]", styles: dict) -> Table:
        if not defects:
            return self._table([["No defects match."]])
        rows = [["Key", "Title", "Severity", "Status", "Developer"]]
        for d in defects:
            rows.append([
                d.defect_key,
                Paragraph(d.title[:110], styles["cell"]),
                d.severity.value, d.status.value,
                d.assigned_developer.full_name if d.assigned_developer else "—",
            ])
        return self._table(
            rows, col_widths=[20 * mm, 80 * mm, 20 * mm, 26 * mm, 32 * mm]
        )
