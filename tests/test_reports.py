"""Phase 8 tests: CSV exports (Google Sheets-ready) and PDF reports."""
from __future__ import annotations

import csv
import io
from datetime import date, timedelta

import pytest

from app.extensions import db
from app.models import DefectStatus, Severity
from app.models.enums import UserRole
from app.utils.datetime import utcnow
from tests.factories import (
    login,
    make_defect,
    make_module,
    make_sprint,
    make_story,
    make_user,
)


@pytest.fixture()
def world(app, client) -> dict:
    qa = make_user(username="rep.qa", full_name="Report QA")
    dev = make_user(role=UserRole.DEVELOPER, full_name="Report Dev")
    module = make_module(name="Payments")
    sprint = make_sprint()
    story = make_story(sprint=sprint)
    open_defect = make_defect(
        qa, module, title="UPI outage ₹ symbol test", severity=Severity.CRITICAL,
        assigned_developer=dev, assigned_qa=qa, sprint=sprint, story=story,
        eta=date.today() + timedelta(days=2),
    )
    closed_defect = make_defect(
        qa, module, title="Closed defect row", status=DefectStatus.CLOSED,
        assigned_developer=dev, sprint=sprint,
        created_at=utcnow() - timedelta(days=3), resolved_at=utcnow(),
    )
    db.session.commit()
    login(client, qa)
    return {
        "qa": qa, "dev": dev, "module": module, "sprint": sprint,
        "story": story, "open": open_defect, "closed": closed_defect,
    }


def _rows(response) -> list:
    text = response.data.decode("utf-8-sig")  # strips the BOM
    return list(csv.reader(io.StringIO(text)))


class TestDefectsCsv:
    def test_full_export_content(self, client, world) -> None:
        response = client.get("/reports/defects.csv")
        assert response.status_code == 200
        assert response.mimetype == "text/csv"
        assert "attachment" in response.headers["Content-Disposition"]
        assert response.data.startswith("﻿".encode("utf-8"))

        rows = _rows(response)
        header, body = rows[0], rows[1:]
        assert header[:4] == ["Key", "Title", "Status", "Severity"]
        assert len(body) == 2

        by_key = {row[0]: row for row in body}
        open_row = by_key[world["open"].defect_key]
        assert open_row[1] == "UPI outage ₹ symbol test"
        assert open_row[header.index("Developer")] == "Report Dev"
        assert open_row[header.index("Sprint")] == world["sprint"].name
        assert open_row[header.index("Story")] == world["story"].key

    def test_respects_defect_list_filters(self, client, world) -> None:
        response = client.get("/reports/defects.csv?state=open")
        body = _rows(response)[1:]
        keys = {row[0] for row in body}
        assert keys == {world["open"].defect_key}

        response = client.get(f"/reports/defects.csv?reporter={world['qa'].id}&state=done")
        body = _rows(response)[1:]
        assert {row[0] for row in body} == {world["closed"].defect_key}

    def test_requires_login(self, app) -> None:
        response = app.test_client().get("/reports/defects.csv")
        assert response.status_code == 302
        assert "/auth/login" in response.headers["Location"]

    def test_export_button_carries_filters(self, client, world) -> None:
        page = client.get("/defects/?state=open&severity=Critical").data
        assert b"/reports/defects.csv?" in page
        assert b"state=open" in page


class TestDevelopersCsv:
    def test_workload_rows(self, client, world) -> None:
        response = client.get("/reports/developers.csv")
        rows = _rows(response)
        header = rows[0]
        by_name = {row[0]: row for row in rows[1:]}

        dev_row = by_name["Report Dev"]
        assert dev_row[header.index("Open assigned")] == "1"
        assert dev_row[header.index("Resolved all-time")] == "1"
        assert dev_row[header.index("Avg resolution (days)")] == "3.0"

        qa_row = by_name["Report QA"]
        assert qa_row[header.index("Open QA queue")] == "1"
        assert qa_row[header.index("Reported")] == "2"


class TestPdfReports:
    def test_summary_pdf(self, client, world) -> None:
        response = client.get("/reports/summary.pdf")
        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        assert response.data.startswith(b"%PDF")
        assert len(response.data) > 1500

    def test_sprint_pdf(self, client, world) -> None:
        response = client.get(f"/reports/sprint/{world['sprint'].id}.pdf")
        assert response.status_code == 200
        assert response.mimetype == "application/pdf"
        assert response.data.startswith(b"%PDF")

    def test_sprint_pdf_missing_sprint_redirects(self, client, world) -> None:
        assert client.get("/reports/sprint/99999.pdf").status_code == 302


class TestHub:
    def test_index_lists_all_reports(self, client, world) -> None:
        page = client.get("/reports/").data
        assert b"Defect export" in page
        assert b"Team workload" in page
        assert b"Sprint report" in page
        assert b"QA summary" in page
        assert world["sprint"].name.encode() in page
